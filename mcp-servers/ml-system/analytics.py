import os
from datetime import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio
import shap
from sklearn.model_selection import train_test_split, cross_val_score, learning_curve, validation_curve
from sklearn.metrics import (roc_curve, auc, confusion_matrix,
                           classification_report, precision_recall_curve)
from sklearn.preprocessing import LabelEncoder
from scipy.stats import spearmanr, chi2_contingency, f_oneway
from scipy.stats.contingency import association
from sklearn.pipeline import Pipeline
import joblib
import warnings
from scipy import stats
import shutil
from utils import save_project_status, read_project_status
from JobStatusManager import create_job, update_job_status
import traceback
warnings.filterwarnings('ignore')

def extract_model_from_pipeline(model):
    """Pipeline에서 최종 모델을 추출한다."""
    if hasattr(model, 'named_steps'):
        return model.steps[-1][1]
    return model

def extract_feature_names_from_pipeline(model, fallback_features):
    """Pipeline preprocessor에서 feature names를 추출한다."""
    if hasattr(model, 'named_steps'):
        for step_name, step in model.named_steps.items():
            if hasattr(step, 'get_feature_names_out'):
                try:
                    return list(step.get_feature_names_out())
                except:
                    continue
            elif hasattr(step, 'feature_names_'):
                return list(step.feature_names_)
    return list(fallback_features)

#region Before Train
def select_features_by_target_correlation(df, numerical_cols, target_column, max_features=20):
    """
    Select top features based on correlation with target variable.
    
    Args:
        df: DataFrame
        numerical_cols: List of numerical column names
        target_column: Target variable name
        max_features: Maximum number of features to select
    
    Returns:
        list: Selected feature names (including target)
    """
    if target_column not in df.columns:
        return numerical_cols[:max_features]
    
    try:
        # Calculate correlations with target
        correlations = df[numerical_cols].corr()[target_column].abs().sort_values(ascending=False)
        
        # Remove target from correlations and select top features
        feature_correlations = correlations[correlations.index != target_column]
        top_features = feature_correlations.head(max_features - 1).index.tolist()
        
        # Include target column at the beginning
        selected_features = [target_column] + top_features
        
        return selected_features
        
    except Exception as e:
        print(f"Error in feature selection: {e}")
        return numerical_cols[:max_features]

def detect_column_types(df, categorical_threshold=0.05, unique_threshold=50, id_threshold=0.999):
    """
    Intelligently detect numerical, categorical, datetime and id-like columns based on data characteristics.
    
    Args:
        df: DataFrame
        categorical_threshold: Ratio threshold for considering a column as categorical
        unique_threshold: Absolute threshold for unique values in categorical columns
        id_threshold: Ratio threshold for considering a column as id-like
    Returns:
        dict: {"column_name": "type", ...}
    """
    column_types = {}
    for col in df.columns:
        col_data = df[col].dropna()
        if len(col_data) == 0:
            column_types[col] = "empty"
            continue

        # 1. Datetime check
        if pd.api.types.is_string_dtype(col_data) or pd.api.types.is_datetime64_any_dtype(col_data):
            try:
                # 첫 10개 데이터를 샘플링하여 datetime으로 변환 시도
                pd.to_datetime(col_data.head(10), errors='raise')
                # 성공하면 전체 데이터에 대해 변환 시도 (더 정확한 확인)
                pd.to_datetime(col_data, errors='raise')
                column_types[col] = "datetime"
                continue
            except (ValueError, TypeError):
                # datetime 변환 실패 시 일반 로직으로 진행
                pass

        # 2. Numeric check
        is_numeric_dtype = pd.api.types.is_numeric_dtype(col_data)
        if is_numeric_dtype:
            unique_count = col_data.nunique()
            total_count = len(col_data)
            unique_ratio = unique_count / total_count if total_count > 0 else 0
            
            # 2a. ID-like check (very high cardinality)
            if unique_ratio >= id_threshold:
                column_types[col] = "identifier"
                continue
            
            # 2b. 정수형과 실수형 구분
            is_integer_dtype = pd.api.types.is_integer_dtype(col_data)
            is_float_dtype = pd.api.types.is_float_dtype(col_data)

            # 실제 값들이 정수인지 확인 (float 타입이지만 정수값만 포함하는 경우)
            has_only_integers = col_data.apply(lambda x: float(x).is_integer()).all() if is_float_dtype else True

            # 정수형인 경우에만 encoded_categorical 가능성 체크
            if is_integer_dtype:
                if (unique_count <= unique_threshold) and (unique_ratio <= categorical_threshold):
                    column_types[col] = "encoded_categorical"
                else:
                    column_types[col] = "numerical"
            # 실수형인 경우는 항상 numerical
            elif is_float_dtype:
                column_types[col] = "numerical"
                if has_only_integers and (unique_count <= unique_threshold) and (unique_ratio <= categorical_threshold):
                    column_types[col] = "encoded_categorical"
            else:
                # 기타 numeric 타입 (boolean 등)
                column_types[col] = "numerical"
        else:
            # 3. Categorical (non-numeric, non-datetime)
            column_types[col] = "categorical"
    
    return column_types

def encode_categorical_columns(df, column_types):
    """
    Encode categorical columns for analysis.
    
    Args:
        df: DataFrame
        column_types: {"column_name": "type", ...}
    Returns:
        df, dict: {"column_name": "type", ...}
    """
    
    df_encoded = df.copy()
    
    for col, col_type in column_types.items():
        # Label encoding
        if (col_type == 'categorical') or (col_type=="encoded_categorical"):
            le = LabelEncoder()
            df_encoded[col] = le.fit_transform(df[col].astype(str))
            column_types[col] = 'encoded_categorical'

    return df_encoded, column_types

def calculate_feature_correlations(df, column_types, target_col):
    """
    Calculate appropriate correlations between features and target based on data types.
    
    Args:
        df: DataFrame with encoded features
        target_col: Target column name
        column_types: Dictionary containing column name and type.
    
    Returns:
        dict: Dictionary of {feature: correlation_value}
    """
    
    correlations = {}
    target_data = df[target_col].dropna()
    
    # Determine target variable type
    target_is_binary = target_data.nunique() == 2
    target_is_continuous = True

    # Check if target was originally categorical
    for feature_col, type in column_types.items():
        if (type == 'encoded_categorical') and (target_col == feature_col):
            target_is_continuous = False
            break
    
    for feature_col, type in column_types.items():
        if feature_col == target_col:
            correlations[feature_col] = 1.0
            continue
            
        feature_data = df[feature_col].dropna()
        
        # Find common indices (non-null for both)
        common_idx = target_data.index.intersection(feature_data.index)
        if len(common_idx) < 2:
            correlations[feature_col] = 0.0
            continue
            
        target_vals = target_data[common_idx]
        feature_vals = feature_data[common_idx]
        
        # Determine feature type
        feature_is_binary = df[feature_col].nunique() == 2
        
        if type == 'numerical':
            feature_is_continuous = True
        else:
            feature_is_continuous = False

        try:
            # Case 1: Continuous vs Continuous
            if feature_is_continuous or target_is_continuous:
                # For binary variables, use Pearson (equivalent to phi coefficient)
                correlation = target_vals.corr(feature_vals, method='pearson')
                
            # Case 2: Categorical vs Continuous (or vice versa)
            elif (feature_is_continuous and not target_is_continuous) or (not feature_is_continuous and target_is_continuous):
                if target_is_continuous:
                    # Feature is categorical (label encoded), target is continuous
                    if feature_is_binary:
                        # Point-biserial correlation for binary categorical
                        correlation = target_vals.corr(feature_vals, method='pearson')
                    else:
                        # Eta coefficient for multi-category label encoded feature
                        # Calculate eta squared (proportion of variance explained)
                        groups = [target_vals[feature_vals == val] for val in feature_vals.unique() if len(target_vals[feature_vals == val]) > 0]
                        if len(groups) > 1:
                            f_stat, p_val = f_oneway(*groups)
                            # Convert F-statistic to eta correlation
                            total_variance = target_vals.var()
                            if total_variance > 0:
                                eta_squared = f_stat * (len(groups) - 1) / (f_stat * (len(groups) - 1) + len(target_vals) - len(groups))
                                correlation = np.sqrt(eta_squared)
                            else:
                                correlation = 0.0
                        else:
                            correlation = 0.0
                else:
                    # Target is categorical (label encoded), feature is continuous
                    if target_is_binary:
                        # Point-biserial correlation
                        correlation = target_vals.corr(feature_vals, method='pearson')
                    else:
                        # Use Spearman for ordinal target with continuous feature
                        correlation, _ = spearmanr(target_vals, feature_vals)
            # Case 3: Categorical vs Categorical (both label encoded)
            elif not feature_is_continuous and not target_is_continuous:
                if feature_is_binary and target_is_binary:
                    # Phi coefficient (equivalent to Pearson for binary)
                    correlation = target_vals.corr(feature_vals, method='pearson')
                else:
                    # For label encoded categorical variables, use Spearman correlation
                    # as it captures monotonic relationships in ordinal data
                    correlation, _ = spearmanr(target_vals, feature_vals)
            
            else:
                # Default fallback to Spearman for label encoded variables
                correlation, _ = spearmanr(target_vals, feature_vals)
           # Handle NaN correlations
            if pd.isna(correlation):
                correlation = 0.0
                
            # Ensure correlation is within valid range
            correlation = np.clip(correlation, -1.0, 1.0)
            
            correlations[feature_col] = correlation

        except Exception as e:
            print(f"Error calculating correlation for {feature_col}: {e}")
            correlations[feature_col] = 0.0
    
    return correlations

def create_eda_visualizations(job_id: str, project_path: str, target_column: str = None, max_features: int = 20) -> str:
    """
    Create comprehensive Exploratory Data Analysis visualizations.
    Each visualization is saved as a separate file for better organization.
    
    Args:
        project_path: path of the project. 
        target_column: Target variable of this project.
        max_features: Maximum number of features to visualize (default: 20)
    Returns:
        String with status message
    """
    # Read project status
    status = read_project_status(project_path)

    create_job(job_id, job_category="eda-visualization")

    if status["data_file"] is None:
        update_job_status(job_id=job_id, step="Fail", error="No data file has been analyzed for this project", progress=100)
        return ""
    
    visualizations_path = os.path.join(project_path, "visualizations")
    
    try:
        # Load data
        df = pd.read_csv(status["data_file"])
        update_job_status(job_id=job_id, step="Detecting Column Types", progress=5)

        # Use the detect_column_types function
        column_types = detect_column_types(df)

        # All analyzable columns (numerical + encoded categorical)
        numerical_cols = [col for col, col_type in column_types.items() if col_type in ['numerical']]
        categorical_cols = [col for col, col_type in column_types.items() if col_type in ['categorical', 'encoded_categorical']]
        analyzable_cols = numerical_cols + categorical_cols

        if len(analyzable_cols) - 1 > max_features:
            feature_selection_applied = True
            update_job_status(job_id=job_id, step="Calculating Feature Correlations", progress=15)
            tmp_df, tmp_column_types = encode_categorical_columns(df, column_types)
            correlations = calculate_feature_correlations(tmp_df, tmp_column_types, target_column)
            input_correlations = {col: abs(corr) for col, corr in correlations.items() 
                                if col != target_column}
            sorted_correlations = sorted(input_correlations.items(), 
                                       key=lambda x: x[1], reverse=True)      

            top_features = [col for col, _ in sorted_correlations[:max_features]]
            
            # Separate selected features by type
            selected_numerical_cols = [col for col in top_features 
                                     if col in numerical_cols]
            categorical_cols = [col for col in top_features 
                                               if col in categorical_cols]
            
            # Add target column back to numerical or encoded categorical
            if target_column in numerical_cols:
                if target_column not in selected_numerical_cols:
                    selected_numerical_cols.append(target_column)
            elif target_column in categorical_cols:
                if target_column not in categorical_cols:
                    categorical_cols.append(target_column)
        else:
            feature_selection_applied=False
            selected_numerical_cols = numerical_cols

        created_files = []
        
        # 1. Missing Values Analysis
        update_job_status(job_id=job_id, step="Missing Values Analysis", progress=5)
        plt.figure(figsize=(12, 8))
        # Use selected columns for missing value analysis
        analysis_cols = selected_numerical_cols + categorical_cols
        missing_data = df[analysis_cols].isnull().sum()
        missing_data = missing_data[missing_data > 0].sort_values(ascending=False)
        
        if len(missing_data) > 0:
            plt.barh(range(len(missing_data)), missing_data.values, color='coral')
            plt.yticks(range(len(missing_data)), missing_data.index)
            plt.xlabel('Number of Missing Values')
            plt.ylabel('Columns')
            plt.title('Missing Values by Column (Selected Features)', fontsize=16, fontweight='bold')
            plt.grid(True, alpha=0.3)
            
            # Add value labels on bars
            for i, v in enumerate(missing_data.values):
                plt.text(v + 0.1, i, str(v), va='center')
        else:
            plt.text(0.5, 0.5, 'No Missing Values Found', ha='center', va='center', 
                    transform=plt.gca().transAxes, fontsize=20, 
                    bbox=dict(boxstyle="round,pad=0.5", facecolor="lightgreen", alpha=0.7))
            plt.title('Missing Values Analysis (Selected Features)', fontsize=16, fontweight='bold')
        
        plt.tight_layout()
        missing_file = 'missing_values_analysis.png'
        plt.savefig(os.path.join(visualizations_path, missing_file), dpi=300, bbox_inches='tight')
        plt.close()
        created_files.append(missing_file)
        
        # 2. Data Types Distribution
        update_job_status(job_id=job_id, step="Data Types Distribution", progress=10)
        plt.figure(figsize=(10, 8))
        dtype_counts = df[analysis_cols].dtypes.value_counts()
        colors = plt.cm.Set3(np.linspace(0, 1, len(dtype_counts)))
        
        wedges, texts, autotexts = plt.pie(dtype_counts.values, labels=dtype_counts.index, 
                                          autopct='%1.1f%%', colors=colors, startangle=90)
        
        # Enhance text appearance
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
        
        plt.title('Data Types Distribution (Selected Features)', fontsize=16, fontweight='bold')
        plt.axis('equal')
        
        dtypes_file = 'data_types_distribution.png'
        plt.savefig(os.path.join(visualizations_path, dtypes_file), dpi=300, bbox_inches='tight')
        plt.close()
        created_files.append(dtypes_file)
        
        # 3. Correlation Heatmap (if enough numerical columns)
        update_job_status(job_id=job_id, step="Correlation Heatmap", progress=20)
        if len(selected_numerical_cols) > 1:
            plt.figure(figsize=(12, 10))
            corr_matrix = df[selected_numerical_cols].corr()
            
            im = plt.imshow(corr_matrix, cmap='coolwarm', aspect='auto', vmin=-1, vmax=1)
            plt.xticks(range(len(selected_numerical_cols)), selected_numerical_cols, rotation=45, ha='right')
            plt.yticks(range(len(selected_numerical_cols)), selected_numerical_cols)
            plt.title('Correlation Matrix (Selected Features)', fontsize=16, fontweight='bold')
            
            # Add correlation values
            for i in range(len(selected_numerical_cols)):
                for j in range(len(selected_numerical_cols)):
                    text = plt.text(j, i, f'{corr_matrix.iloc[i, j]:.2f}',
                                   ha="center", va="center", 
                                   color="black" if abs(corr_matrix.iloc[i, j]) < 0.5 else "white",
                                   fontweight='bold')
            
            # Add colorbar
            cbar = plt.colorbar(im, fraction=0.046, pad=0.04)
            cbar.set_label('Correlation Coefficient', rotation=270, labelpad=20)
            
            plt.tight_layout()
            corr_file = 'correlation_matrix.png'
            plt.savefig(os.path.join(visualizations_path, corr_file), dpi=300, bbox_inches='tight')
            plt.close()
            created_files.append(corr_file)
        
        # 4. Pair Plot (limited to prevent performance issues)
        update_job_status(job_id=job_id, step="Pair Plot", progress=30)
        if len(selected_numerical_cols) >= 2:
            try:
                # Limit to first 6 numerical columns to prevent excessive computation
                pair_cols = selected_numerical_cols[:6] if len(selected_numerical_cols) > 6 else selected_numerical_cols
                
                # Create pair plot with categorical hue if available
                if len(categorical_cols) > 0:
                    # Use the categorical column with reasonable number of categories
                    hue_col = None
                    for cat_col in categorical_cols:
                        if 2 <= df[cat_col].nunique() <= 8:  # Optimal range for color coding
                            hue_col = cat_col
                            break
                    
                    if hue_col:
                        g = sns.pairplot(df[pair_cols + [hue_col]], hue=hue_col, corner=True, 
                                       plot_kws={'alpha': 0.6}, diag_kind='hist')
                    else:
                        g = sns.pairplot(df[pair_cols], corner=True, 
                                       plot_kws={'alpha': 0.6}, diag_kind='hist')
                else:
                    g = sns.pairplot(df[pair_cols], corner=True, 
                                   plot_kws={'alpha': 0.6}, diag_kind='hist')
                
                g.fig.suptitle('Pair Plot of Selected Numerical Variables', y=1.02, size=16)
                pair_file = 'pair_plot.png'
                g.savefig(os.path.join(visualizations_path, pair_file), dpi=300, bbox_inches='tight')
                plt.close()
                created_files.append(pair_file)
                
            except ImportError:
                print("Seaborn not available for pair plot generation")
            except Exception as e:
                print(f"Error creating pair plot: {e}")
        
        # 5. Categorical vs Numerical Analysis (Box Plots)
        update_job_status(job_id=job_id, step="Categorical vs Numerical Analysis", progress=40)
        if len(categorical_cols) > 0 and len(selected_numerical_cols) > 0:
            for cat_col in categorical_cols:
                if 2 <= df[cat_col].nunique() <= 15:  # Reasonable number of categories
                    # Create a summary plot with multiple numerical variables
                    n_num_cols = min(4, len(selected_numerical_cols))  # Max 4 subplots
                    
                    if n_num_cols == 1:
                        fig, ax = plt.subplots(1, 1, figsize=(10, 6))
                        axes = [ax]
                    else:
                        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
                        axes = axes.flatten()
                    
                    for i, num_col in enumerate(selected_numerical_cols[:n_num_cols]):
                        try:
                            sns.boxplot(data=df, x=cat_col, y=num_col, ax=axes[i])
                            axes[i].set_title(f'{num_col} by {cat_col}', fontsize=12, fontweight='bold')
                            axes[i].tick_params(axis='x', rotation=45)
                            axes[i].grid(True, alpha=0.3)
                        except ImportError:
                            # Fallback to matplotlib boxplot if seaborn is not available
                            categories = df[cat_col].unique()
                            box_data = [df[df[cat_col] == cat][num_col].dropna() for cat in categories]
                            axes[i].boxplot(box_data, labels=categories)
                            axes[i].set_title(f'{num_col} by {cat_col}', fontsize=12, fontweight='bold')
                            axes[i].tick_params(axis='x', rotation=45)
                            axes[i].grid(True, alpha=0.3)
                    
                    # Hide unused subplots
                    for j in range(n_num_cols, len(axes)):
                        axes[j].set_visible(False)
                    
                    plt.tight_layout()
                    boxplot_file = f'boxplot_analysis_{cat_col.replace(" ", "_").replace("/", "_")}.png'
                    plt.savefig(os.path.join(visualizations_path, boxplot_file), dpi=300, bbox_inches='tight')
                    plt.close()
                    created_files.append(boxplot_file)
        
        # 6. Q-Q Plots for Normality Testing
        update_job_status(job_id=job_id, step="Q-Q Plots", progress=50)
        if len(selected_numerical_cols) > 0:
            try:
                # Create Q-Q plots for selected numerical columns
                n_cols = len(selected_numerical_cols)
                n_rows = (n_cols + 2) // 3  # 3 columns per row
                
                fig, axes = plt.subplots(n_rows, 3, figsize=(15, 5*n_rows))
                if n_rows == 1:
                    axes = axes.reshape(1, -1)
                
                for i, col in enumerate(selected_numerical_cols):
                    row, col_idx = divmod(i, 3)
                    
                    stats.probplot(df[col].dropna(), dist="norm", plot=axes[row, col_idx])
                    axes[row, col_idx].set_title(f'Q-Q Plot: {col}', fontsize=10, fontweight='bold')
                    axes[row, col_idx].grid(True, alpha=0.3)
                
                # Hide unused subplots
                for j in range(n_cols, n_rows * 3):
                    row, col_idx = divmod(j, 3)
                    axes[row, col_idx].set_visible(False)
                
                plt.tight_layout()
                qq_file = 'qq_plots_normality.png'
                plt.savefig(os.path.join(visualizations_path, qq_file), dpi=300, bbox_inches='tight')
                plt.close()
                created_files.append(qq_file)
                
            except ImportError:
                print("Scipy not available for Q-Q plot generation")
            except Exception as e:
                print(f"Error creating Q-Q plots: {e}")
        
        # 7. Dataset Information Summary
        update_job_status(job_id=job_id, step="Dataset Information Summary", progress=60)
        plt.figure(figsize=(14, 10))
        
        # Calculate additional statistics
        duplicate_count = df.duplicated().sum()
        memory_usage = df.memory_usage(deep=True).sum() / 1024**2
        
        # Missing value summary
        missing_summary = df[analysis_cols].isnull().sum()
        missing_cols = missing_summary[missing_summary > 0]
        
        # Outlier detection for selected numerical columns (using IQR method)
        outlier_summary = {}
        for col in selected_numerical_cols:
            Q1 = df[col].quantile(0.25)
            Q3 = df[col].quantile(0.75)
            IQR = Q3 - Q1
            outliers = df[(df[col] < Q1 - 1.5*IQR) | (df[col] > Q3 + 1.5*IQR)][col]
            outlier_summary[col] = len(outliers)
        
        feature_selection_info = ""
        if feature_selection_applied:
            feature_selection_info = f"""
FEATURE SELECTION
Applied: Yes (Original: {len(numerical_cols)} → Selected: {len(selected_numerical_cols)} numerical features)
Target Variable: {target_column}
Selection Method: Correlation-based"""
        
        info_text = f"""DATASET OVERVIEW
Shape: {df.shape[0]:,} rows × {df.shape[1]} columns
Memory Usage: {memory_usage:.2f} MB
Duplicate Rows: {duplicate_count:,} ({duplicate_count/len(df)*100:.1f}%)
{feature_selection_info}

VARIABLE TYPES (Selected)
Numerical Columns: {len(selected_numerical_cols)}
Categorical Columns: {len(categorical_cols)}

MISSING VALUES (Selected Features)
Total Missing: {df[analysis_cols].isnull().sum().sum():,}
Columns with Missing Data: {len(missing_cols)}
{('Top Missing: ' + ', '.join([f'{col}({cnt})' for col, cnt in missing_cols.head(5).items()])) if len(missing_cols) > 0 else 'No Missing Values'}

OUTLIERS (IQR Method - Selected Features)
{chr(10).join([f'{col}: {count:,} outliers' for col, count in list(outlier_summary.items())[:8]])}

SELECTED NUMERICAL COLUMNS
{', '.join(selected_numerical_cols[:15])}{'...' if len(selected_numerical_cols) > 15 else ''}

SELECTED CATEGORICAL COLUMNS  
{', '.join(categorical_cols[:10])}{'...' if len(categorical_cols) > 10 else ''}"""
        
        plt.text(0.05, 0.95, info_text, transform=plt.gca().transAxes, 
                fontsize=11, verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle="round,pad=0.5", facecolor="lightblue", alpha=0.8))
        plt.xlim(0, 1)
        plt.ylim(0, 1)
        plt.axis('off')
        plt.title('Enhanced Dataset Information Summary (Selected Features)', fontsize=16, fontweight='bold', pad=20)
        
        info_file = 'dataset_info_summary.png'
        plt.savefig(os.path.join(visualizations_path, info_file), dpi=300, bbox_inches='tight')
        plt.close()
        created_files.append(info_file)
        
        # 8. Numerical Distributions (individual plots) - Enhanced
        update_job_status(job_id=job_id, step="Numerical Distributions", progress=70)
        if len(selected_numerical_cols) > 0:
            for col in selected_numerical_cols:
                fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
                
                # Histogram with KDE
                data = df[col].dropna()
                n, bins, patches = ax1.hist(data, bins=30, alpha=0.7, 
                                          color='skyblue', edgecolor='black', density=True)
                
                # Add KDE overlay
                try:
                    if len(data) > 1:
                        kde = stats.gaussian_kde(data)
                        x_range = np.linspace(data.min(), data.max(), 100)
                        ax1.plot(x_range, kde(x_range), color='red', linewidth=2, label='KDE')
                        ax1.legend()
                except:
                    pass
                
                # Enhanced statistics
                mean_val = data.mean()
                median_val = data.median()
                std_val = data.std()
                skew_val = data.skew() if len(data) > 1 else 0
                
                stats_text = f"Mean: {mean_val:.2f}\nMedian: {median_val:.2f}\nStd: {std_val:.2f}\nSkewness: {skew_val:.2f}"
                ax1.axvline(mean_val, color='red', linestyle='--', alpha=0.7, label=f'Mean: {mean_val:.2f}')
                ax1.axvline(median_val, color='green', linestyle='--', alpha=0.7, label=f'Median: {median_val:.2f}')
                
                ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes, 
                        verticalalignment='top', fontsize=10,
                        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))
                
                ax1.set_title(f'Distribution of {col}', fontsize=14, fontweight='bold')
                ax1.set_xlabel(col)
                ax1.set_ylabel('Density')
                ax1.grid(True, alpha=0.3)
                
                # Box plot
                ax2.boxplot(data, vert=True, patch_artist=True, 
                           boxprops=dict(facecolor='lightblue', alpha=0.7))
                ax2.set_title(f'Box Plot of {col}', fontsize=14, fontweight='bold')
                ax2.set_ylabel(col)
                ax2.grid(True, alpha=0.3)
                
                plt.tight_layout()
                
                dist_file = f'distribution_{col.replace(" ", "_").replace("/", "_")}.png'
                plt.savefig(os.path.join(visualizations_path, dist_file), dpi=300, bbox_inches='tight')
                plt.close()
                created_files.append(dist_file)
        
        # 9. Categorical Distributions (individual plots) - Enhanced
        update_job_status(job_id=job_id, step="Categorical Distributions", progress=80)
        if len(categorical_cols) > 0:
            for col in categorical_cols:
                fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
                
                value_counts = df[col].value_counts()
                # Limit to top 20 categories for readability
                if len(value_counts) > 20:
                    value_counts_plot = value_counts.head(20)
                    title_suffix = f" (Top 20 out of {df[col].nunique()})"
                else:
                    value_counts_plot = value_counts
                    title_suffix = ""
                
                # Bar plot
                bars = ax1.bar(range(len(value_counts_plot)), value_counts_plot.values, 
                              color=plt.cm.viridis(np.linspace(0, 1, len(value_counts_plot))))
                
                ax1.set_xticks(range(len(value_counts_plot)))
                ax1.set_xticklabels(value_counts_plot.index, rotation=45, ha='right')
                ax1.set_title(f'Distribution of {col}{title_suffix}', fontsize=14, fontweight='bold')
                ax1.set_xlabel(col)
                ax1.set_ylabel('Count')
                ax1.grid(True, alpha=0.3, axis='y')
                
                # Add value labels on bars
                for i, v in enumerate(value_counts_plot.values):
                    ax1.text(i, v + 0.01 * max(value_counts_plot.values), str(v), 
                            ha='center', va='bottom', fontsize=9)
                
                # Pie chart for better proportion view
                if len(value_counts_plot) <= 10:  # Only for reasonable number of categories
                    ax2.pie(value_counts_plot.values, labels=value_counts_plot.index, 
                           autopct='%1.1f%%', startangle=90)
                    ax2.set_title(f'Proportion of {col}', fontsize=14, fontweight='bold')
                else:
                    # Show summary statistics instead
                    summary_text = f"""Unique Values: {df[col].nunique():,}
Most Frequent: {value_counts.index[0]} ({value_counts.iloc[0]:,})
Least Frequent: {value_counts.index[-1]} ({value_counts.iloc[-1]:,})
Missing Values: {df[col].isnull().sum():,}

Top 10 Categories:
{chr(10).join([f'{idx}: {val:,}' for idx, val in value_counts.head(10).items()])}"""
                    
                    ax2.text(0.05, 0.95, summary_text, transform=ax2.transAxes, 
                            fontsize=10, verticalalignment='top', fontfamily='monospace',
                            bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8))
                    ax2.set_xlim(0, 1)
                    ax2.set_ylim(0, 1)
                    ax2.axis('off')
                    ax2.set_title(f'Summary of {col}', fontsize=14, fontweight='bold')
                
                plt.tight_layout()
                
                cat_file = f'distribution_{col.replace(" ", "_").replace("/", "_")}.png'
                plt.savefig(os.path.join(visualizations_path, cat_file), dpi=300, bbox_inches='tight')
                plt.close()
                created_files.append(cat_file)
        
        # 10. Interactive Plotly Dashboard
        update_job_status(job_id=job_id, step="Interactive Plotly Dashboard", progress=90)
        if len(selected_numerical_cols) >= 2:
            # Create enhanced subplot structure
            subplot_titles = ['Variable Relationships', 'Distribution Comparison', 
                            'Correlation Heatmap', 'Statistical Summary']
            fig = make_subplots(
                rows=2, cols=2,
                subplot_titles=subplot_titles,
                specs=[[{"type": "scatter"}, {"type": "histogram"}],
                       [{"type": "heatmap"}, {"type": "table"}]]
            )
            
            # Enhanced scatter plot with additional features
            fig.add_trace(
                go.Scatter(x=df[selected_numerical_cols[0]], y=df[selected_numerical_cols[1]], 
                          mode='markers', name=f'{selected_numerical_cols[0]} vs {selected_numerical_cols[1]}',
                          marker=dict(size=8, opacity=0.7, color='blue',
                                    line=dict(width=1, color='white')),
                          hovertemplate=f'{selected_numerical_cols[0]}: %{{x}}<br>{selected_numerical_cols[1]}: %{{y}}<extra></extra>'),
                row=1, col=1
            )
            
            # Enhanced histograms with statistics
            for i, col in enumerate(selected_numerical_cols[:3]):
                fig.add_trace(
                    go.Histogram(x=df[col], name=col, opacity=0.7, nbinsx=30,
                               hovertemplate=f'{col}<br>Range: %{{x}}<br>Count: %{{y}}<extra></extra>'),
                    row=1, col=2
                )
            
            # Enhanced correlation heatmap (reuses corr_matrix computed in matplotlib section above)
            fig.add_trace(
                go.Heatmap(z=corr_matrix.values, 
                          x=corr_matrix.columns, 
                          y=corr_matrix.columns,
                          colorscale='RdBu',
                          zmid=0,
                          text=corr_matrix.round(2).values,
                          texttemplate="%{text}",
                          textfont={"size": 10},
                          hovertemplate='%{x} vs %{y}<br>Correlation: %{z}<extra></extra>'),
                row=2, col=1
            )
            
            # Statistical summary table
            summary_stats = df[selected_numerical_cols].describe().round(2)
            fig.add_trace(
                go.Table(
                    header=dict(values=['Statistic'] + list(summary_stats.columns),
                               fill_color='lightblue',
                               align='left'),
                    cells=dict(values=[summary_stats.index] + [summary_stats[col] for col in summary_stats.columns],
                              fill_color='white',
                              align='left')),
                row=2, col=2
            )
            
            fig.update_layout(
                height=900, 
                showlegend=True, 
                title_text="Enhanced Interactive Data Exploration Dashboard (Selected Features)",
                title_font_size=18,
                title_x=0.5
            )
            
            interactive_file = 'enhanced_interactive_dashboard.html'
            fig.write_html(os.path.join(visualizations_path, interactive_file))
            created_files.append(interactive_file)
        
        # Update project status
        status["visualizations"]["eda"] = {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "files": created_files,
            "total_files": len(created_files),
            "features": {
                "pair_plot": len(selected_numerical_cols) >= 2,
                "categorical_analysis": len(categorical_cols) > 0 and len(selected_numerical_cols) > 0,
                "qq_plots": len(selected_numerical_cols) > 0,
                "enhanced_summary": True,
                "interactive_dashboard": len(selected_numerical_cols) >= 2
            }
        }
        save_project_status(project_path, status)
        update_job_status(job_id=job_id, step="Complete", progress=100)
        
        # Return success message with feature selection info
        success_message = f"EDA visualizations created successfully. Generated {len(created_files)} files."
        if feature_selection_applied:
            success_message += f"\nFeature selection applied: {len(numerical_cols)} → {len(selected_numerical_cols)} numerical features based on correlation with '{target_column}'."
        
        return success_message
        
    except Exception as e:
        traceback.print_exc()
        update_job_status(job_id=job_id, step="Failed", progress=100, message="", error=str(e))

def basic_analyze_data(job_id: str, project_path, file: str) -> str:
    """
    Analyze a CSV file and update the project status.
    Args:
        project_path: path of project.
        file: Path to the CSV file to analyze.
    Returns:
        String with data analysis results.
    """

    try:
        create_job(job_id, job_category="analyze_data")

        update_job_status(job_id=job_id, step="Reading data", progress=20, message="Loading CSV file")
        status = read_project_status(project_path)
        
        data_dir = os.path.join(project_path, "data")
        os.makedirs(data_dir, exist_ok=True)
        file_name = os.path.basename(file)
        destination = os.path.join(data_dir, file_name)

        if file != destination:
            shutil.copy(file, destination)

        df = pd.read_csv(destination)

        update_job_status(job_id=job_id, step="divide data", progress=35, message="divide data into numerical and categorical")
        column_types = detect_column_types(df, categorical_threshold=0.05, unique_threshold=50, id_threshold=0.95)
        numerical_columns = [col for col, col_type in column_types.items() if col_type in ['numerical']]
        categorical_columns = [col for col, col_type in column_types.items() if col_type in ['encoded_categorical', 'categorical']]

        update_job_status(job_id=job_id, step="base analysis", progress=45, message="base analysis")

        # 기존 summary
        analysis_result = {
            "file_name": file_name,
            "file_path": destination,
            "n_rows": len(df),
            "n_columns": len(df.columns),
            "columns": list(df.columns),
            "dtypes": {col: str(df[col].dtype) for col in df.columns},
            "missing_values": {col: int(df[col].isna().sum()) for col in df.columns},
            "missing_percentage": {col: float(df[col].isna().mean() * 100) for col in df.columns},
            "numerical_columns": numerical_columns,
            "categorical_columns": categorical_columns,
            "summary_stats": {}
        }

        # 추가 데이터 품질 정보
        analysis_result.update({
            "duplicate_rows": int(df.duplicated().sum()),
            "unique_values": {col: int(df[col].nunique()) for col in df.columns},
            "data_types_distribution": {str(k): int(v) for k, v in df.dtypes.value_counts().to_dict().items()},
            "memory_usage_bytes": int(df.memory_usage(deep=True).sum()),
        })

        update_job_status(job_id=job_id, step="data quality issue", progress=60, message="data quality issue")

        quality_issues = []
        if df.duplicated().sum() > 0:
            quality_issues.append(f"{df.duplicated().sum()} duplicate rows found")
        for col in df.columns:
            missing_pct = df[col].isna().sum() / len(df)
            if missing_pct > 0.5:
                quality_issues.append(f"Column '{col}' has {missing_pct:.1%} missing values")
            if missing_pct > 0.9:
                quality_issues.append(f"Column '{col}' is mostly empty ({missing_pct:.1%} missing)")
        analysis_result["quality_issues"] = quality_issues

        update_job_status(job_id=job_id, step="statistics", progress=75, message="statistics")

        # Numerical column summary
        for col in analysis_result["numerical_columns"]:
            analysis_result["summary_stats"][col] = {
                "mean": float(df[col].mean()) if not pd.isna(df[col].mean()) else None,
                "median": float(df[col].median()) if not pd.isna(df[col].median()) else None,
                "std": float(df[col].std()) if not pd.isna(df[col].std()) else None,
                "min": float(df[col].min()) if not pd.isna(df[col].min()) else None,
                "max": float(df[col].max()) if not pd.isna(df[col].max()) else None,
                "q25": float(df[col].quantile(0.25)) if not pd.isna(df[col].quantile(0.25)) else None,
                "q75": float(df[col].quantile(0.75)) if not pd.isna(df[col].quantile(0.75)) else None,
                "skewness": float(df[col].skew()) if not pd.isna(df[col].skew()) else None,
                "kurtosis": float(df[col].kurtosis()) if not pd.isna(df[col].kurtosis()) else None
            }
        # Categorical column summary
        for col in analysis_result["categorical_columns"]:
            top_values = df[col].value_counts().head(5).to_dict()
            analysis_result["summary_stats"][col] = {
                "unique_count": int(df[col].nunique()),
                "top_values": {str(k): int(v) for k, v in top_values.items()},
                "most_frequent": str(df[col].mode().iloc[0]) if not df[col].mode().empty else None,
                "least_frequent": str(df[col].value_counts().tail(1).index[0]) if len(df[col].value_counts()) > 0 else None
            }

        # [추가] 피처 간 상관계수 행렬 계산 (수치형만 우선)
        correlation_matrix = None
        if len(numerical_columns) > 1:
            correlation_matrix = df[numerical_columns].corr().round(4).to_dict()

        analysis_result["feature_correlation_matrix"] = correlation_matrix

        # [추가] 타깃 컬럼과 각 feature의 상관계수 계산
        # 예: 타깃 컬럼을 임의로 마지막 컬럼으로 지정하거나, 사용자가 status["target_column"] 등에 지정했다고 가정
        target_col = status.get("target_column") if "target_column" in status else df.columns[-1]
        feature_target_correlations = calculate_feature_correlations(df, column_types, target_col)
        analysis_result["feature_target_correlations"] = feature_target_correlations

        update_job_status(job_id=job_id, step="Saving results", progress=90, message="Saving analysis results")
        status["data_file"] = destination
        status["data_analysis"] = analysis_result
        status["features"] = list(df.columns)
        save_project_status(project_path, status)

        update_job_status(job_id=job_id, step="Complete", progress=100, message="Data analysis completed")

    except Exception as e:
        update_job_status(job_id=job_id, step="Failed", progress=100, message="", error=str(e))

#endregion

#region After Train
def create_advanced_model_visualizations(p_job_id:str, project_path: str, status_job_id:str, rank:int = 1) -> str:
    """
    Create advanced model performance visualizations including learning curves,
    validation curves, confusion matrix, and prediction analysis.

    Args:
        p_job_id: process job id
        project_path: Absolute project directory path
        status_job_id: job id contain trained model infomation
    
    Returns:
        String with status message
    """
    create_job(p_job_id, job_category="advanced model visializations")

    try:
        # Read project status
        update_job_status(job_id=p_job_id, step="status load", progress=0)
        status = read_project_status(project_path)
        
        results_path = os.path.join(project_path, "results")
        os.makedirs(results_path, exist_ok=True)
        viz_path = os.path.join(results_path, status_job_id)
        os.makedirs(viz_path, exist_ok=True)
    
        model_info = status["models"][status_job_id]
        target = model_info["target"]
        task_type = model_info["task_type"]
        model_type = model_info['type']
        test_size = model_info['test_size']
        random_state = model_info['random_state']

        # Load model — pipeline_path is inside top_models[rank]
        update_job_status(job_id=p_job_id, step="model load", progress=10)
        top_models = model_info.get("top_models", {})
        if not top_models:
            update_job_status(job_id=p_job_id, step="No trained model found", progress=-1)
            return "No trained model found in project status"
        # Select model by rank (1-based)
        sorted_keys = sorted(top_models.keys())
        rank_idx = max(0, min(rank - 1, len(sorted_keys) - 1))
        selected_key = sorted_keys[rank_idx]
        selected_model_entry = top_models[selected_key]
        model_path = selected_model_entry["pipeline_path"]
        model = joblib.load(model_path)
        # Use the feature subset that the selected model was actually trained on
        features_extracted = selected_model_entry.get("features_used", model_info.get("key_features", []) + model_info.get("explore_features", []))

        # Load data
        update_job_status(job_id=p_job_id, step="data load", progress=20)
        df = pd.read_csv(status["data_file"])
        X = df[features_extracted]
        y = df[target]
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=(y if task_type == "classification" else None)
        )

        # task_type에 따른 scoring metric 선택
        if task_type.lower() == 'regression':
            # 회귀의 경우 R² score 사용 (높을수록 좋음)
            scoring = 'r2'
            ylabel = 'R² Score'
        elif task_type.lower() == 'classification':
            # 분류의 경우 이진/다중 클래스 구분
            if len(np.unique(y_train)) == 2:
                # 이진 분류의 경우 AUROC 사용
                scoring = 'roc_auc'
                ylabel = 'AUROC Score'
            else:
                # 다중 클래스의 경우 accuracy 사용
                scoring = 'accuracy'
                ylabel = 'Accuracy Score'

        saved_files = []
        
        # 1. Learning Curves
        update_job_status(job_id=p_job_id, step="learning curves", progress=30)
        plt.figure(figsize=(12, 8))
        


        train_sizes, train_scores, val_scores = learning_curve(
            model, X_train, y_train, cv=3, n_jobs=4,
            train_sizes=np.linspace(0.1, 1.0, 6),
            scoring=scoring,
            random_state=42
        )

        plt.plot(train_sizes, np.mean(train_scores, axis=1), 'o-', color='blue', label='Training Score', linewidth=2, markersize=6)
        plt.plot(train_sizes, np.mean(val_scores, axis=1), 'o-', color='red', label='Validation Score', linewidth=2, markersize=6)
        plt.fill_between(train_sizes, np.mean(train_scores, axis=1) - np.std(train_scores, axis=1),
                        np.mean(train_scores, axis=1) + np.std(train_scores, axis=1), alpha=0.1, color='blue')
        plt.fill_between(train_sizes, np.mean(val_scores, axis=1) - np.std(val_scores, axis=1),
                        np.mean(val_scores, axis=1) + np.std(val_scores, axis=1), alpha=0.1, color='red')
        plt.xlabel('Training Set Size', fontsize=12)
        plt.ylabel(ylabel, fontsize=12)
        plt.title(f'Learning Curves ({scoring.upper()})', fontsize=14, fontweight='bold')
        plt.legend(fontsize=11)
        plt.grid(True, alpha=0.3)

        learning_curve_path = os.path.join(viz_path, '01_learning_curves.png')
        plt.savefig(learning_curve_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()
        saved_files.append(learning_curve_path)

        # 2. Confusion Matrix (for classification)
        if task_type == "classification":
            update_job_status(job_id=p_job_id, step="confusion matrix", progress=40)
            y_pred = model.predict(X_test)
            cm = confusion_matrix(y_test, y_pred)
            
            plt.figure(figsize=(10, 8))
            sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', 
                       xticklabels=np.unique(y), yticklabels=np.unique(y),
                       cbar_kws={'shrink': 0.8})
            plt.title('Confusion Matrix', fontsize=14, fontweight='bold')
            plt.ylabel('True Label', fontsize=12)
            plt.xlabel('Predicted Label', fontsize=12)
            
            confusion_matrix_path = os.path.join(viz_path, '02_confusion_matrix.png')
            plt.savefig(confusion_matrix_path, dpi=300, bbox_inches='tight', facecolor='white')
            plt.close()
            saved_files.append(confusion_matrix_path)

            # Compute y_proba once for binary classification
            if len(np.unique(y)) == 2 and hasattr(model, "predict_proba"):
                y_proba = model.predict_proba(X_test)[:, 1]

            # 3. Precision-Recall Curve (for binary classification)
            if len(np.unique(y)) == 2 and hasattr(model, "predict_proba"):
                update_job_status(job_id=p_job_id, step="precision-recall curve", progress=35)
                plt.figure(figsize=(10, 8))
                precision, recall, _ = precision_recall_curve(y_test, y_proba)
                plt.plot(recall, precision, color='darkorange', lw=3)
                plt.xlabel('Recall', fontsize=12)
                plt.ylabel('Precision', fontsize=12)
                plt.title('Precision-Recall Curve', fontsize=14, fontweight='bold')
                plt.grid(True, alpha=0.3)

                pr_curve_path = os.path.join(viz_path, '03_precision_recall_curve.png')
                plt.savefig(pr_curve_path, dpi=300, bbox_inches='tight', facecolor='white')
                plt.close()
                saved_files.append(pr_curve_path)

            # 4. ROC-AUC Curve with Confidence Interval (for binary classification)
            if len(np.unique(y)) == 2 and hasattr(model, "predict_proba"):
                update_job_status(job_id=p_job_id, step="roc-auc curve", progress=37)

                # Calculate ROC curve
                fpr, tpr, _ = roc_curve(y_test, y_proba)
                roc_auc = auc(fpr, tpr)
                
                # Bootstrap for confidence interval
                n_bootstrap = 200
                n_samples = len(y_test)
                aucs = []
                
                for i in range(n_bootstrap):
                    # Bootstrap sample
                    indices = np.random.choice(n_samples, n_samples, replace=True)
                    y_test_boot = y_test.iloc[indices]
                    y_proba_boot = y_proba[indices]
                    
                    # Calculate AUC for bootstrap sample
                    try:
                        fpr_boot, tpr_boot, _ = roc_curve(y_test_boot, y_proba_boot)
                        auc_boot = auc(fpr_boot, tpr_boot)
                        aucs.append(auc_boot)
                    except:
                        continue
                
                # Calculate confidence interval
                aucs = np.array(aucs)
                ci_lower = np.percentile(aucs, 2.5)
                ci_upper = np.percentile(aucs, 97.5)
                
                # Create plot
                plt.figure(figsize=(10, 8))
                plt.plot(fpr, tpr, color='darkorange', lw=3, 
                         label=f'ROC curve (AUC = {roc_auc:.3f}, 95% CI: {ci_lower:.3f}-{ci_upper:.3f})')
                plt.plot([0, 1], [0, 1], color='navy', lw=2, linestyle='--', label='Random Classifier')
                plt.xlim([0.0, 1.0])
                plt.ylim([0.0, 1.05])
                plt.xlabel('False Positive Rate', fontsize=12)
                plt.ylabel('True Positive Rate', fontsize=12)
                plt.title(f'ROC Curve - {model_type.replace("_", " ").title()}', fontsize=14, fontweight='bold')
                plt.legend(loc="lower right", fontsize=11)
                plt.grid(True, alpha=0.3)
                
                # Add confidence interval text
                plt.text(0.6, 0.2, f'Bootstrap CI (n={n_bootstrap})', fontsize=10, 
                         bbox=dict(boxstyle="round,pad=0.3", facecolor="lightgray", alpha=0.5))
                
                roc_auc_path = os.path.join(viz_path, '04_roc_auc_curve.png')
                plt.savefig(roc_auc_path, dpi=300, bbox_inches='tight', facecolor='white')
                plt.close()
                saved_files.append(roc_auc_path)

        # 5. Residual Plot (for regression)
        if task_type == "regression":
            update_job_status(job_id=p_job_id, step="residual plot", progress=25)
            y_pred = model.predict(X_test)
            residuals = y_test - y_pred
            
            plt.figure(figsize=(10, 8))
            plt.scatter(y_pred, residuals, alpha=0.7, color='blue', s=50)
            plt.axhline(y=0, color='red', linestyle='--', linewidth=2)
            plt.xlabel('Predicted Values', fontsize=12)
            plt.ylabel('Residuals', fontsize=12)
            plt.title('Residual Plot', fontsize=14, fontweight='bold')
            plt.grid(True, alpha=0.3)
            
            residual_plot_path = os.path.join(viz_path, '05_residual_plot.png')
            plt.savefig(residual_plot_path, dpi=300, bbox_inches='tight', facecolor='white')
            plt.close()
            saved_files.append(residual_plot_path)

            # 6. Predicted vs Actual
            update_job_status(job_id=p_job_id, step="predicted vs actual", progress=35)
            plt.figure(figsize=(10, 8))
            plt.scatter(y_test, y_pred, alpha=0.7, color='green', s=50)
            plt.plot([y_test.min(), y_test.max()], [y_test.min(), y_test.max()], 'r--', lw=2)
            plt.xlabel('Actual Values', fontsize=12)
            plt.ylabel('Predicted Values', fontsize=12)
            plt.title('Predicted vs Actual', fontsize=14, fontweight='bold')
            plt.grid(True, alpha=0.3)
            
            pred_vs_actual_path = os.path.join(viz_path, '06_predicted_vs_actual.png')
            plt.savefig(pred_vs_actual_path, dpi=300, bbox_inches='tight', facecolor='white')
            plt.close()
            saved_files.append(pred_vs_actual_path)



        # 8. Cross-validation scores
        update_job_status(job_id=p_job_id, step="cross-validation scores", progress=55)
        cv_scores = cross_val_score(model, X, y, cv=5, scoring=scoring)
        
        plt.figure(figsize=(10, 8))
        bars = plt.bar(range(1, 6), cv_scores, color='lightcoral', edgecolor='darkred', linewidth=2)
        plt.axhline(y=cv_scores.mean(), color='red', linestyle='--', linewidth=2, 
                   label=f'Mean: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}')
        plt.xlabel('Fold', fontsize=12)
        plt.ylabel('Score', fontsize=12)
        plt.title('Cross-Validation Scores', fontsize=14, fontweight='bold')
        plt.legend(fontsize=11)
        plt.grid(True, alpha=0.3, axis='y')
        
        # Add value labels on bars
        for i, (bar, score) in enumerate(zip(bars, cv_scores)):
            plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                    f'{score:.3f}', ha='center', va='bottom', fontsize=10)
        
        cv_scores_path = os.path.join(viz_path, '08_cross_validation_scores.png')
        plt.savefig(cv_scores_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()
        saved_files.append(cv_scores_path)
        # 9. validation curve
        update_job_status(job_id=p_job_id, step="Model Complexity Analysis", progress=65)
        if model_type == "random_forest":
            param_name = 'model__n_estimators'  # For pipeline
            param_range = [50, 100, 200]
        elif model_type == "decision_tree":
            param_name = 'model__max_depth'  # For pipeline
            param_range = [3, 5, 7, 10, 15, 20]
        else:
            param_name = None
        
        if param_name:
            plt.figure(figsize=(12, 8))
            try:
                train_scores, val_scores = validation_curve(
                    model, X, y, param_name=param_name, param_range=param_range,
                    cv=3, scoring=scoring
                )
                
                train_mean = np.mean(train_scores, axis=1)
                train_std = np.std(train_scores, axis=1)
                val_mean = np.mean(val_scores, axis=1)
                val_std = np.std(val_scores, axis=1)
                
                plt.plot(param_range, train_mean, 'o-', color='blue', label='Training', 
                        linewidth=2, markersize=8)
                plt.plot(param_range, val_mean, 'o-', color='red', label='Validation', 
                        linewidth=2, markersize=8)
                
                plt.fill_between(param_range, train_mean - train_std, train_mean + train_std, 
                               alpha=0.1, color='blue')
                plt.fill_between(param_range, val_mean - val_std, val_mean + val_std, 
                               alpha=0.1, color='red')
                
                plt.xlabel(param_name.split('__')[-1].replace('_', ' ').title(), fontsize=12)
                plt.ylabel('Score', fontsize=12)
                plt.title(f'Validation Curve ({param_name.split("__")[-1].replace("_", " ").title()})', 
                         fontsize=14, fontweight='bold')
                plt.legend(fontsize=11)
                plt.grid(True, alpha=0.3)
                
                validation_curve_path = os.path.join(viz_path, '09_validation_curve.png')
                plt.savefig(validation_curve_path, dpi=300, bbox_inches='tight', facecolor='white')
                plt.close()
                saved_files.append(validation_curve_path)

            except Exception as e:
                print(f"Warning: Could not create validation curve: {e}")
                plt.figure(figsize=(10, 6))
                plt.text(0.5, 0.5, 'Validation Curve\nNot Available\n\n' + str(e), 
                        ha='center', va='center', transform=plt.gca().transAxes,
                        fontsize=12, bbox=dict(boxstyle="round,pad=0.3", facecolor="lightgray"))
                plt.title('Validation Curve', fontsize=14, fontweight='bold')
                plt.axis('off')
                validation_curve_path = os.path.join(viz_path, '09_validation_curve_unavailable.png')
                plt.savefig(validation_curve_path, dpi=300, bbox_inches='tight', facecolor='white')
                plt.close()
                saved_files.append(validation_curve_path)

        # Create detailed classification report (for classification)
        if task_type == "classification":
            update_job_status(job_id=p_job_id, step="classification report", progress=70)
            report = classification_report(y_test, y_pred, output_dict=True)
            
            # Create classification report visualization
            plt.figure(figsize=(12, 8))
            
            # Convert report to DataFrame for better visualization
            report_df = pd.DataFrame(report).transpose()
            report_df = report_df.iloc[:-3, :-1]  # Remove macro/weighted avg and support
            
            # Create heatmap
            sns.heatmap(report_df, annot=True, fmt='.3f', cmap='Blues', 
                       cbar_kws={'shrink': 0.8}, linewidths=0.5)
            plt.title('Classification Report Heatmap', fontsize=14, fontweight='bold')
            plt.ylabel('Classes', fontsize=12)
            plt.xlabel('Metrics', fontsize=12)
            
            classification_report_path = os.path.join(viz_path, '10_classification_report.png')
            plt.savefig(classification_report_path, dpi=300, bbox_inches='tight', facecolor='white')
            plt.close()
            saved_files.append(classification_report_path)

        # shap plots
        update_job_status(job_id=p_job_id, step="shap plots", progress=80)
        generate_shap_plots(model, X_train, X_test, features_extracted, viz_path, model_type, task_type)

        # Update project status
        update_job_status(job_id=p_job_id, step="updating status", progress=85)
        if "visualizations" not in status:
            status["visualizations"] = {}
        
        status["visualizations"][f"{status_job_id}_advanced"] = {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "files": saved_files
        }
        save_project_status(project_path, status)
        update_job_status(job_id=p_job_id, step="complete", progress=100)
        
        
    except Exception as e:
        update_job_status(job_id=p_job_id, step="error occur", progress=100, error= str(e))

def generate_importance_table(p_job_id:str, project_path: str, status_job_id:str, rank:int = 1) -> str:
    """Generate feature importance table and visualization"""

    create_job(p_job_id, job_category="generate importance table")
    try:
        # Read project status
        update_job_status(job_id=p_job_id, step="status load", progress=15)
        status = read_project_status(project_path)

        results_path = os.path.join(project_path, "results")
        os.makedirs(results_path, exist_ok=True)
        viz_path = os.path.join(results_path, status_job_id)
        os.makedirs(viz_path, exist_ok=True)

        model_info = status["models"][status_job_id]
        model_type = model_info['type']

        # Load model — pipeline_path is inside top_models[rank]
        update_job_status(job_id=p_job_id, step="model load", progress=30)
        top_models = model_info.get("top_models", {})
        if not top_models:
            update_job_status(job_id=p_job_id, step="No trained model found", progress=-1)
            return "No trained model found in project status"
        # Select model by rank (1-based)
        sorted_keys = sorted(top_models.keys())
        rank_idx = max(0, min(rank - 1, len(sorted_keys) - 1))
        selected_key = sorted_keys[rank_idx]
        selected_model_info = top_models[selected_key]
        model_path = selected_model_info["pipeline_path"]
        model = joblib.load(model_path)

        # Get actual feature names from the model/pipeline
        final_model = extract_model_from_pipeline(model)
        feature_names = extract_feature_names_from_pipeline(model, selected_model_info.get("features_used", model_info.get("key_features", []) + model_info.get("explore_features", [])))
        
        # Get feature importance
        importance = None
        if hasattr(final_model, 'feature_importances_'):
            importance = final_model.feature_importances_
        elif hasattr(final_model, 'coef_'):
            importance = np.abs(final_model.coef_).flatten()
        else:
            update_job_status(job_id=p_job_id, step="Model doesn't support feature importance", progress=-1)
            return "Model doesn't support feature importance"


        # Ensure we have the right number of features
        if len(feature_names) != len(importance):
            # Try to get original feature names if available
            original_features = selected_model_info.get("features_used", model_info.get("key_features", []) + model_info.get("explore_features", []))
            if len(original_features) == len(importance):
                feature_names = original_features
                print("Warning: Using original feature list due to dimension mismatch.")
            else:
                update_job_status(job_id=p_job_id, step=f"Feature dimension mismatch: {len(feature_names)} vs {len(importance)}", progress=-1)
                return f"Feature dimension mismatch: {len(feature_names)} features vs {len(importance)} importance values"

        update_job_status(job_id=p_job_id, step="Create importance table", progress=50)
        # Create importance dataframe
        importance_df = pd.DataFrame({
            'Feature': feature_names,
            'Importance': importance
        }).sort_values('Importance', ascending=False)
        
        # Normalize importance to percentages
        importance_df['Importance_Pct'] = (importance_df['Importance'] / 
                                        importance_df['Importance'].sum()) * 100
        
        # Create visualization
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
        
        # Bar plot
        colors = plt.cm.viridis(np.linspace(0, 1, len(importance_df)))
        bars = ax1.barh(importance_df['Feature'], importance_df['Importance'], color=colors)
        ax1.set_xlabel('Feature Importance', fontsize=12)
        ax1.set_title(f'Feature Importance - {model_type.replace("_", " ").title()}', 
                    fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3, axis='x')
        
        # Add value labels on bars
        for i, bar in enumerate(bars):
            width = bar.get_width()
            ax1.text(width + width*0.01, bar.get_y() + bar.get_height()/2, 
                    f'{importance_df.iloc[i]["Importance"]:.4f}', 
                    ha='left', va='center', fontsize=10)
        
        # Table
        ax2.axis('tight')
        ax2.axis('off')
        
        # Create table data
        table_data = []
        for idx, row in importance_df.iterrows():
            table_data.append([
                row['Feature'],
                f"{row['Importance']:.4f}",
                f"{row['Importance_Pct']:.2f}%"
            ])
        
        table = ax2.table(cellText=table_data,
                        colLabels=['Feature', 'Importance', 'Percentage'],
                        cellLoc='center',
                        loc='center',
                        bbox=[0, 0, 1, 1])
        
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 2)
        
        # Style the table
        for i in range(len(table_data) + 1):
            for j in range(3):
                cell = table[(i, j)]
                if i == 0:  # Header
                    cell.set_facecolor('#4CAF50')
                    cell.set_text_props(weight='bold', color='white')
                else:
                    if i % 2 == 0:
                        cell.set_facecolor('#f2f2f2')
                    else:
                        cell.set_facecolor('white')
        
        ax2.set_title('Feature Importance Table', fontsize=14, fontweight='bold', pad=20)

        update_job_status(job_id=p_job_id, step="Save importance table", progress=100)
        plt.tight_layout()
        plt.savefig(os.path.join(viz_path, f'additional_{model_type}_importance_table.png'), 
                    dpi=300, bbox_inches='tight')
        plt.close()
        
        # Save CSV
        importance_df.to_csv(os.path.join(viz_path, f'additional_{model_type}_importance.csv'), 
                            index=False)
    except Exception as e:
        update_job_status(job_id=p_job_id, step="Error occur", progress=-1, error=str(e))

def generate_shap_plots(model, X_train, X_test, features, results_path, model_type, task_type):
    """Generate SHAP analysis plots with Pipeline support"""
    try:
        # Handle Pipeline objects (sklearn Pipeline and imblearn ImbPipeline)
        if hasattr(model, 'named_steps') and hasattr(model, 'steps'):
            # Get the final estimator (actual model)
            final_model = extract_model_from_pipeline(model)

            # Extract only the preprocessor step (skip SMOTE and model)
            # SMOTE's transform() is not usable at inference time,
            # so we must call the preprocessor directly
            preprocessor = model.named_steps.get('preprocessor')
            if preprocessor is not None:
                X_train_transformed = preprocessor.transform(X_train)
                X_test_transformed = preprocessor.transform(X_test)

                # Update feature names if transformation changed them
                if hasattr(preprocessor, 'get_feature_names_out'):
                    try:
                        transformed_features = list(preprocessor.get_feature_names_out(features))
                    except Exception:
                        transformed_features = [f"feature_{i}" for i in range(X_train_transformed.shape[1])]
                else:
                    if hasattr(X_train_transformed, 'shape'):
                        n_cols = X_train_transformed.shape[1] if len(X_train_transformed.shape) > 1 else 1
                    else:
                        n_cols = len(features)
                    if n_cols != len(features):
                        transformed_features = [f"feature_{i}" for i in range(n_cols)]
                    else:
                        transformed_features = features
            else:
                # No preprocessor step — use data as-is
                X_train_transformed = X_train
                X_test_transformed = X_test
                transformed_features = features

            # ✅ DataFrame 확실히 생성하고 인덱스 리셋
            X_train_for_shap = pd.DataFrame(
                X_train_transformed,
                columns=transformed_features
            ).reset_index(drop=True)

            X_test_for_shap = pd.DataFrame(
                X_test_transformed,
                columns=transformed_features
            ).reset_index(drop=True)

            features_for_shap = transformed_features
            actual_model = final_model
            
        else:
            # Regular model - DataFrame 확인 및 변환
            actual_model = model
            # ✅ 확실히 DataFrame으로 변환
            if not isinstance(X_train, pd.DataFrame):
                X_train_for_shap = pd.DataFrame(X_train, columns=features)
                X_test_for_shap = pd.DataFrame(X_test, columns=features)
            else:
                X_train_for_shap = X_train.copy()
                X_test_for_shap = X_test.copy()
            features_for_shap = features
        
        # Create explainer based on model type
        tree_models = ['random_forest', 'xgboost', 'decision_tree', 'lightgbm', 'catboost', 'extra_trees']
        use_kernel = False
        if model_type in tree_models:
            try:
                explainer = shap.TreeExplainer(actual_model)
                shap_values = explainer.shap_values(X_test_for_shap.values)

                # For binary classification, take positive class
                if task_type == "classification" and isinstance(shap_values, list):
                    shap_values = shap_values[1] if len(shap_values) == 2 else shap_values[0]
            except Exception:
                # TreeExplainer failed (e.g. XGBoost/SHAP version incompatibility)
                use_kernel = True

        else:
            use_kernel = True

        if use_kernel:
            # KernelExplainer fallback — data is already preprocessor-transformed,
            # so call actual_model.predict directly
            background = shap.kmeans(X_train_for_shap.values, min(50, len(X_train_for_shap)))
            explainer = shap.KernelExplainer(actual_model.predict, background)
            shap_values = explainer.shap_values(X_test_for_shap.iloc[:100].values)
        
        # SHAP 값이 3차원인 경우 (이진 분류) - 올바른 차원으로 변환
        if len(shap_values.shape) == 3 and shap_values.shape[2] == 2:
            shap_values_for_plot = shap_values[:, :, 1]
        elif len(shap_values.shape) == 2:
            shap_values_for_plot = shap_values
        else:
            shap_values_for_plot = shap_values

        # 1. Summary plot
        plt.figure(figsize=(12, 10))
        shap.summary_plot(
            shap_values_for_plot, 
            X_test_for_shap.values,  # numpy array 전달
            feature_names=features_for_shap,  # 명시적으로 feature names 전달
            max_display=len(features_for_shap), 
            show=False
        )
        plt.title(f'SHAP Summary Plot - {model_type.replace("_", " ").title()}', 
                fontsize=14, fontweight='bold', pad=20)
        plt.subplots_adjust(top=0.9, bottom=0.1)
        plt.tight_layout()
        plt.savefig(os.path.join(results_path, f'{model_type}_shap_summary.png'), 
                    dpi=300, bbox_inches='tight')
        plt.close()
        
        # 2. Bar plot
        plt.figure(figsize=(10, 10))
        shap.summary_plot(
            shap_values_for_plot, 
            X_test_for_shap.values,  # numpy array 전달
            feature_names=features_for_shap,  # 명시적으로 feature names 전달
            plot_type="bar", 
            max_display=len(features_for_shap), 
            show=False
        )
        plt.title(f'SHAP Feature Importance - {model_type.replace("_", " ").title()}', 
                fontsize=14, fontweight='bold', pad=20)
        plt.subplots_adjust(top=0.9, bottom=0.1)
        plt.tight_layout()
        plt.savefig(os.path.join(results_path, f'{model_type}_shap_bar.png'), 
                    dpi=300, bbox_inches='tight')
        plt.close()
        
        # 3. Waterfall plot for first prediction
        if hasattr(shap, 'waterfall_plot'):
            plt.figure(figsize=(12, 8))
            # Handle expected_value for different explainer types
            if hasattr(explainer, 'expected_value'):
                expected_value = explainer.expected_value
                if isinstance(expected_value, (list, np.ndarray)) and len(expected_value) > 1:
                    expected_value = expected_value[1] if task_type == "classification" else expected_value[0]
            else:
                expected_value = 0
            
            # Use the same processed SHAP values for waterfall plot
            waterfall_shap_values = shap_values_for_plot[0]  # First sample
            waterfall_expected = expected_value
            
            # Create SHAP Explanation object for waterfall plot
            explanation = shap.Explanation(
                values=waterfall_shap_values, 
                base_values=waterfall_expected, 
                data=X_test_for_shap.iloc[0]
            )
            shap.waterfall_plot(explanation, show=False)
            
            plt.title(f'SHAP Waterfall Plot (First Prediction) - {model_type.replace("_", " ").title()}', 
                    fontsize=14, fontweight='bold')
            plt.tight_layout()
            plt.savefig(os.path.join(results_path, f'{model_type}_shap_waterfall.png'), 
                        dpi=300, bbox_inches='tight')
            plt.close()
        
    except Exception as e:
        print(f"SHAP analysis failed: {str(e)}")
        # Create a simple message plot
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, f'SHAP analysis not available\nfor {model_type}\n\nError: {str(e)}', 
                horizontalalignment='center', verticalalignment='center',
                transform=ax.transAxes, fontsize=14,
                bbox=dict(boxstyle="round,pad=0.5", facecolor="lightcoral", alpha=0.7))
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        plt.title(f'SHAP Analysis - {model_type.replace("_", " ").title()}', 
                fontsize=16, fontweight='bold')
        plt.tight_layout()
        plt.savefig(os.path.join(results_path, f'{model_type}_shap_error.png'), 
                    dpi=300, bbox_inches='tight')
        plt.close()

#endregion
