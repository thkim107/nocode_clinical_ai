import os
from itertools import combinations
from typing import List
from datetime import datetime
import pandas as pd
from sklearn.model_selection import train_test_split, GridSearchCV, StratifiedKFold, KFold
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
from sklearn.linear_model import LogisticRegression, LinearRegression
import xgboost as xgb
from sklearn.metrics import (accuracy_score, roc_auc_score, roc_curve, precision_score,
                             recall_score, f1_score, mean_squared_error, r2_score)
from sklearn.preprocessing import StandardScaler, OrdinalEncoder, LabelEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
import lightgbm as lgb
from catboost import CatBoostClassifier, CatBoostRegressor
from sklearn.ensemble import ExtraTreesClassifier, ExtraTreesRegressor
from imblearn.pipeline import Pipeline as ImbPipeline
from imblearn.over_sampling import SMOTE
import joblib
import numpy as np
import warnings
from utils import save_project_status, read_project_status
from JobStatusManager import create_job, update_job_status
from analytics import detect_column_types
warnings.filterwarnings('ignore')


# =============================================================================
# feature_selection 관련 함수들은 feature combination analysis 로 대체됨
# 기존 feature_selection, _rfe_selection, _boruta_shap_selection,
# _selectkbest_mi_selection, _rf_importance_selection 함수 제거
# =============================================================================


def _build_preprocessor(X, categorical_threshold=0.05, unique_threshold=50, id_threshold=0.95):
    """데이터프레임에 맞는 전처리 파이프라인을 구축한다."""
    column_types = detect_column_types(X, categorical_threshold=categorical_threshold,
                                       unique_threshold=unique_threshold, id_threshold=id_threshold)
    numeric_features = [col for col, col_type in column_types.items() if col_type == 'numerical']
    categorical_features = [col for col, col_type in column_types.items() if col_type == 'categorical']

    numeric_transformer = Pipeline(steps=[
        ('imputer', SimpleImputer(strategy='mean')),
        ('scaler', StandardScaler())
    ])
    categorical_transformer = Pipeline(steps=[
        ('imputer', SimpleImputer(strategy='most_frequent')),
        ('onehot', OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1))
    ])
    preprocessor = ColumnTransformer(
        transformers=[
            ('num', numeric_transformer, numeric_features),
            ('cat', categorical_transformer, categorical_features)
        ],
        remainder='passthrough'
    )
    return preprocessor


def _get_model_and_params(model_type, task_type, random_state, job_dir=None):
    """모델 객체와 하이퍼파라미터 그리드를 반환한다."""
    is_classification = task_type == "classification"

    models = {
        "random_forest": (RandomForestClassifier(random_state=random_state),
                          RandomForestRegressor(random_state=random_state)),
        "xgboost": (xgb.XGBClassifier(random_state=random_state, eval_metric='logloss'),
                    xgb.XGBRegressor(random_state=random_state, eval_metric='rmse')),
        "lightgbm": (lgb.LGBMClassifier(random_state=random_state),
                     lgb.LGBMRegressor(random_state=random_state)),
        "catboost": (CatBoostClassifier(random_state=random_state, train_dir=job_dir, verbose=0),
                     CatBoostRegressor(random_state=random_state, train_dir=job_dir, verbose=0)),
        "decision_tree": (DecisionTreeClassifier(random_state=random_state),
                          DecisionTreeRegressor(random_state=random_state)),
        "extra_trees": (ExtraTreesClassifier(random_state=random_state),
                        ExtraTreesRegressor(random_state=random_state)),
        "linear_regression": (LogisticRegression(random_state=random_state, max_iter=1000),
                              LinearRegression())
    }

    param_grids = {
        "random_forest": {'model__n_estimators': [100, 200], 'model__max_depth': [10, 20, None]},
        "xgboost": {'model__n_estimators': [200, 500], 'model__learning_rate': [0.01, 0.03, 0.05]},
        "lightgbm": {'model__n_estimators': [200, 500], 'model__learning_rate': [0.01, 0.03, 0.05]},
        "catboost": {'model__iterations': [200, 500], 'model__learning_rate': [0.01, 0.03, 0.05]},
        "decision_tree": {'model__max_depth': [5, 10, None]},
        "extra_trees": {'model__n_estimators': [100, 200], 'model__max_depth': [10, 20, None]},
        "linear_regression": {'model__C': [0.1, 1.0, 10.0]} if is_classification else {}
    }

    model = models[model_type][0] if is_classification else models[model_type][1]
    param_grid = param_grids[model_type]
    return model, param_grid


def _build_pipeline(preprocessor, model, is_classification, use_smote, random_state):
    """전처리 + 모델 파이프라인을 구축한다."""
    pipeline_steps = [('preprocessor', preprocessor)]
    if is_classification and use_smote:
        pipeline_steps.append(('smote', SMOTE(random_state=random_state)))
        pipeline_steps.append(('model', model))
        return ImbPipeline(steps=pipeline_steps)
    else:
        pipeline_steps.append(('model', model))
        return Pipeline(steps=pipeline_steps)


def _cv_auc_with_roc(pipeline, X, y, cv_folds, random_state):
    """
    StratifiedKFold CV로 AUC + 95% CI(percentile) + fold별 ROC 데이터를 수집한다.
    Returns:
        mean_auc, ci_low, ci_high, fold_aucs, roc_records
    """
    kf = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=random_state)
    fold_aucs = []
    roc_records = []
    base_fpr = np.linspace(0, 1, 100)

    for fold_idx, (train_idx, test_idx) in enumerate(kf.split(X, y)):
        X_train_fold, X_test_fold = X.iloc[train_idx], X.iloc[test_idx]
        y_train_fold, y_test_fold = y.iloc[train_idx], y.iloc[test_idx]

        pipeline.fit(X_train_fold, y_train_fold)

        if hasattr(pipeline, "predict_proba"):
            y_proba = pipeline.predict_proba(X_test_fold)
            if y_proba.shape[1] == 2:
                y_score = y_proba[:, 1]
            else:
                fold_aucs.append(np.nan)
                continue
        else:
            fold_aucs.append(np.nan)
            continue

        fold_auc = roc_auc_score(y_test_fold, y_score)
        fold_aucs.append(fold_auc)

        fpr, tpr, _ = roc_curve(y_test_fold, y_score)
        tpr_interp = np.interp(base_fpr, fpr, tpr)
        tpr_interp[0] = 0.0

        for j, (fpr_val, tpr_val) in enumerate(zip(base_fpr, tpr_interp)):
            roc_records.append({
                'fold': fold_idx + 1,
                'auc': fold_auc,
                'fpr': fpr_val,
                'tpr': tpr_val
            })

    valid_aucs = [a for a in fold_aucs if not np.isnan(a)]
    if valid_aucs:
        mean_auc = float(np.mean(valid_aucs))
        ci_low = float(np.percentile(valid_aucs, 2.5))
        ci_high = float(np.percentile(valid_aucs, 97.5))
    else:
        mean_auc, ci_low, ci_high = 0.0, 0.0, 0.0

    return mean_auc, ci_low, ci_high, fold_aucs, roc_records


def train_model(
    job_id: str,
    project_path: str,
    key_features: list,
    explore_features: list,
    target: str,
    task_type: str,
    model_type: str = "random_forest",
    test_size: float = 0.2,
    random_state: int = 42,
    use_smote: bool = False,
    cv_folds: int = 5
) -> str:
    """
    Feature combination analysis + model training.

    1. key_features + explore_features 조합 생성 (explore 최대 2개씩)
    2. 각 조합별 StratifiedKFold CV → AUC + 95% CI (percentile)
    3. AUC 상위 10개 선정
    4. 상위 10개 각각 GridSearchCV 학습 + test_predictions 저장
    5. 전체 combination_results.csv, roc_data.csv 저장
    """
    create_job(job_id, job_category="train model")

    try:
        # =====================================================================
        # 1. 데이터 로드 & 검증
        # =====================================================================
        update_job_status(job_id=job_id, step="Load data", progress=0)
        status = read_project_status(project_path)
        models_dir = os.path.join(project_path, "models")
        os.makedirs(models_dir, exist_ok=True)
        job_dir = os.path.join(models_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)

        data_file = status.get("data_file")
        df = pd.read_csv(data_file)

        update_job_status(job_id=job_id, step="Validate data", progress=5)
        all_feature_cols = list(set(key_features + explore_features))
        available_key = [f for f in key_features if f in df.columns]
        available_explore = [f for f in explore_features if f in df.columns]
        if not available_key:
            raise ValueError("Error: None of the specified key_features were found in the dataset.")
        if target not in df.columns:
            raise ValueError(f"Error: Target column '{target}' not found in the dataset.")

        is_classification = task_type == "classification"

        # 타겟 변수 전처리
        y = df[target].copy()
        label_encoder = None
        if is_classification:
            if y.dtype == 'object' or isinstance(y.iloc[0], str):
                label_encoder = LabelEncoder()
                y = pd.Series(label_encoder.fit_transform(y), index=y.index)

        # =====================================================================
        # 2. 피처 조합 생성
        # =====================================================================
        update_job_status(job_id=job_id, step="Generate combinations", progress=10)
        feature_combinations = []

        # (a) Key only
        feature_combinations.append(("Key only", available_key[:]))

        # (b) Key + explore 1개씩
        for var in available_explore:
            feature_combinations.append((f"Key + {var}", available_key + [var]))

        # (c) Key + explore 2개 조합
        if len(available_explore) >= 2:
            for combo in combinations(available_explore, 2):
                combo_name = " + ".join(combo)
                feature_combinations.append((f"Key + {combo_name}", available_key + list(combo)))

        # =====================================================================
        # 3. 각 조합별 CV AUC 평가
        # =====================================================================
        update_job_status(job_id=job_id, step="CV evaluation", progress=15)
        combination_results = []
        all_roc_records = []

        total_combos = len(feature_combinations)
        for i, (combo_name, combo_features) in enumerate(feature_combinations):
            progress = 15 + int(45 * (i + 1) / total_combos)
            update_job_status(job_id=job_id, step=f"CV: {combo_name}", progress=progress)

            X_combo = df[combo_features]

            # 간단한 파이프라인으로 CV 평가
            preprocessor = _build_preprocessor(X_combo)
            model, _ = _get_model_and_params(model_type, task_type, random_state, job_dir)
            pipeline = _build_pipeline(preprocessor, model, is_classification, use_smote, random_state)

            if is_classification:
                mean_auc, ci_low, ci_high, fold_aucs, roc_records = _cv_auc_with_roc(
                    pipeline, X_combo, y, cv_folds, random_state
                )
                for rec in roc_records:
                    rec['model'] = combo_name
                all_roc_records.extend(roc_records)
            else:
                # regression: KFold CV with R2
                kf = KFold(n_splits=cv_folds, shuffle=True, random_state=random_state)
                fold_scores = []
                for train_idx, test_idx in kf.split(X_combo):
                    X_tr, X_te = X_combo.iloc[train_idx], X_combo.iloc[test_idx]
                    y_tr, y_te = y.iloc[train_idx], y.iloc[test_idx]
                    pipeline.fit(X_tr, y_tr)
                    fold_scores.append(r2_score(y_te, pipeline.predict(X_te)))
                mean_auc = float(np.mean(fold_scores))
                ci_low = float(np.percentile(fold_scores, 2.5))
                ci_high = float(np.percentile(fold_scores, 97.5))

            combination_results.append({
                "Model": combo_name,
                "Mean_AUC": mean_auc,
                "CI_Low": ci_low,
                "CI_High": ci_high,
                "AUC_formatted": f"{mean_auc:.3f} ({ci_low:.3f}-{ci_high:.3f})",
                "n_features": len(combo_features),
                "features": combo_features
            })

        # 결과 정렬 & 전체 저장
        results_df = pd.DataFrame(combination_results).sort_values("Mean_AUC", ascending=False).reset_index(drop=True)
        results_df_save = results_df.drop(columns=["features"])
        results_df_save.to_csv(os.path.join(job_dir, "combination_results.csv"), index=False)

        # ROC 데이터 저장 (상위 10개만)
        top_n = min(10, len(results_df))
        top_model_names = results_df.head(top_n)["Model"].tolist()

        if all_roc_records:
            roc_df = pd.DataFrame(all_roc_records)
            roc_df_top = roc_df[roc_df["model"].isin(top_model_names)]
            roc_df_top.to_csv(os.path.join(job_dir, "roc_data.csv"), index=False)

        # =====================================================================
        # 4. 상위 10개 GridSearchCV 학습 + test_predictions 저장
        # =====================================================================
        update_job_status(job_id=job_id, step="Train top models", progress=65)
        top_models_info = {}

        for rank_idx in range(top_n):
            row = results_df.iloc[rank_idx]
            combo_name = row["Model"]
            combo_features = row["features"]
            rank_label = f"rank_{rank_idx + 1:02d}_{combo_name.replace(' ', '_')}"

            progress = 65 + int(25 * (rank_idx + 1) / top_n)
            update_job_status(job_id=job_id, step=f"Train: {combo_name}", progress=progress)

            rank_dir = os.path.join(job_dir, rank_label)
            os.makedirs(rank_dir, exist_ok=True)

            X_combo = df[combo_features]

            # train/test split
            X_train, X_test, y_train, y_test = train_test_split(
                X_combo, y, test_size=test_size, random_state=random_state,
                stratify=(y if is_classification else None)
            )

            # 파이프라인 & GridSearchCV
            preprocessor = _build_preprocessor(X_combo)
            model, param_grid = _get_model_and_params(model_type, task_type, random_state, rank_dir)
            pipeline = _build_pipeline(preprocessor, model, is_classification, use_smote, random_state)

            cv_strategy = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=random_state) if is_classification else cv_folds
            scoring = 'f1_macro' if is_classification else 'r2'
            grid_search = GridSearchCV(pipeline, param_grid=param_grid, cv=cv_strategy,
                                       n_jobs=-1, verbose=0, scoring=scoring)
            grid_search.fit(X_train, y_train)
            best_pipeline = grid_search.best_estimator_

            # 모델 저장
            model_path = os.path.join(rank_dir, f"{model_type}_pipeline.pkl")
            joblib.dump(best_pipeline, model_path)
            if label_encoder:
                joblib.dump(label_encoder, os.path.join(rank_dir, "label_encoder.pkl"))

            # 평가 메트릭
            y_pred = best_pipeline.predict(X_test)
            if is_classification:
                metrics = {
                    "accuracy": float(accuracy_score(y_test, y_pred)),
                    "precision": float(precision_score(y_test, y_pred, average='macro', zero_division=0)),
                    "recall": float(recall_score(y_test, y_pred, average='macro', zero_division=0)),
                    "f1": float(f1_score(y_test, y_pred, average='macro', zero_division=0)),
                    "roc_auc": None,
                    "cv_mean_auc": float(row["Mean_AUC"]),
                    "cv_ci_low": float(row["CI_Low"]),
                    "cv_ci_high": float(row["CI_High"]),
                }
                if hasattr(best_pipeline, "predict_proba"):
                    y_proba = best_pipeline.predict_proba(X_test)
                    if y_proba.shape[1] == 2:
                        metrics["roc_auc"] = float(roc_auc_score(y_test, y_proba[:, 1]))
                    else:
                        metrics["roc_auc"] = float(roc_auc_score(y_test, y_proba, multi_class='ovr'))
            else:
                mse = mean_squared_error(y_test, y_pred)
                metrics = {
                    "r2": float(r2_score(y_test, y_pred)),
                    "mse": float(mse),
                    "rmse": float(np.sqrt(mse)),
                    "mae": float(np.mean(np.abs(y_test - y_pred))),
                    "cv_mean_r2": float(row["Mean_AUC"]),
                    "cv_ci_low": float(row["CI_Low"]),
                    "cv_ci_high": float(row["CI_High"]),
                }

            # test_predictions.csv 저장
            pred_df = pd.DataFrame({"true_label": y_test.values, "predicted_label": y_pred})
            if is_classification and hasattr(best_pipeline, "predict_proba"):
                y_proba_all = best_pipeline.predict_proba(X_test)
                if y_proba_all.shape[1] == 2:
                    pred_df["predicted_probability"] = y_proba_all[:, 1]
            pred_df.index = X_test.index
            pred_df.index.name = "original_index"
            pred_df.to_csv(os.path.join(rank_dir, "test_predictions.csv"), index=True)

            top_models_info[rank_label] = {
                "rank": rank_idx + 1,
                "combination": combo_name,
                "features_used": combo_features,
                "best_params": grid_search.best_params_,
                "best_cv_score": float(grid_search.best_score_),
                "test_metrics": metrics,
                "pipeline_path": model_path,
            }

        # =====================================================================
        # 5. project_status.json 업데이트
        # =====================================================================
        update_job_status(job_id=job_id, step="Save results", progress=95)

        model_info = {
            "type": model_type,
            "key_features": available_key,
            "explore_features": available_explore,
            "target": target,
            "task_type": task_type,
            "test_size": test_size,
            "random_state": random_state,
            "cv_folds": cv_folds,
            "use_smote": use_smote,
            "total_combinations": len(feature_combinations),
            "top_n_trained": top_n,
            "combination_results_path": os.path.join(job_dir, "combination_results.csv"),
            "roc_data_path": os.path.join(job_dir, "roc_data.csv"),
            "top_models": top_models_info,
            "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        if "models" not in status:
            status["models"] = {}
        status["models"][job_id] = model_info
        save_project_status(project_path, status)

        update_job_status(job_id=job_id, step="Complete", progress=100)

    except Exception as e:
        import traceback
        traceback.print_exc()
        update_job_status(job_id=job_id, step="Error occur", progress=100, message="", error=str(e))
