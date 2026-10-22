import logging
from mcp.server.fastmcp import FastMCP
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import seaborn as sns
import plotly.io as pio
import warnings
import uuid
import asyncio
from analytics import create_eda_visualizations, basic_analyze_data, create_advanced_model_visualizations, generate_importance_table
from modeling import train_model
from utils import _check_inside, create_project, get_project_status
from JobStatusManager import get_job_status_by_id, get_latest_n_status


warnings.filterwarnings('ignore')

# Initialize FastMCP server
mcp = FastMCP(
    "ML-tools",
    host="0.0.0.0",
    stateless_http=True
)

# Set plotting style
plt.style.use('default')
sns.set_palette("husl")
pio.templates.default = "plotly_white"
font_path = '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'
font_entry = fm.FontEntry(fname=font_path, name='NanumGothic')
fm.fontManager.ttflist.append(font_entry)
plt.rc('font', family='NanumGothic')

@mcp.tool()
async def new_project(name: str):
    """
    Create a new machine learning project with the specified name at the given local path. Execute this tool only when there is a user request.
    Args:
        name (str): Project name
    """
    result = await create_project(name)
    return result

@mcp.tool()
async def run_data_analyze(project_path: str, file: str):
    """
    Analyze a CSV file and update the project status.
    Args:
        project_path (str): Absolute project directory path
        file (str): Absolute path of the CSV file to analyze
    """
    try:
        _check_inside(project_path)
        _check_inside(file)
    except ValueError as e:
        return str(e)
    
    job_id = str(uuid.uuid4())

    asyncio.create_task(asyncio.to_thread(basic_analyze_data, job_id, project_path, file))

    return f"Analyze data started. Job ID: {job_id}. Do not utilize other tools until the user asks"

@mcp.tool()
async def run_eda_visualizations(project_path: str, target_column:str, max_features:int=20):
    """
    Create comprehensive Exploratory Data Analysis visualizations.
    Each visualization is saved as a separate file for better organization.
    Args:
        project_path (str): Absolute project directory path
        target_column (str): Target variable of this project.
        max_features (int): Maximum number of features to visualize (default: 20)
    Returns:
        String with job_id. results will be saved in project_status.json
    """
    try:
        _check_inside(project_path)
    except ValueError as e:
        return str(e)
    job_id = str(uuid.uuid4())
    asyncio.create_task(asyncio.to_thread(create_eda_visualizations, job_id, project_path, target_column, max_features))

    return f"EDA visualization started. Job ID: {job_id}. Do not utilize other tools until the user asks"

# run_feature_selection 은 run_model_training 의 feature combination analysis 로 대체됨
# @mcp.tool()
# async def run_feature_selection(project_path: str, target: str, methods: list = ['rfe', 'boruta_shap'], task_type: str = 'classification', n_features: int = None, random_state: int = 42):
#     ...

@mcp.tool()
async def run_model_training(
    project_path: str,
    key_features: list,
    explore_features: list,
    target: str,
    task_type: str,
    model_type: str,
    test_size: float = 0.2,
    random_state: int = 42,
    use_smote: bool = False,
    cv_folds: int = 5
):
    """
    Train ML models with automatic feature combination analysis.
    Generates combinations of key + explore features, evaluates each via cross-validation,
    and trains the top 10 models with GridSearchCV.

    Before run this tool, always check the args asking to user.

    Args:
        project_path (str): Absolute project directory path
        key_features (list): Core feature columns always included in every model.
        explore_features (list): Additional feature columns to combine (up to 2 at a time). Can be empty list.
        target (str): Name of the target column for prediction.
        task_type (str): 'classification' or 'regression'
        model_type (str): Type of model to train. Options: random_forest, xgboost, lightgbm, catboost, decision_tree, extra_trees, linear_regression.
        test_size (float, optional): Proportion of dataset to use for testing (default: 0.2).
        random_state (int, optional): Random seed for reproducibility (default: 42).
        use_smote (bool, optional): Whether to apply SMOTE for handling class imbalance (default: False).
        cv_folds (int, optional): Number of cross-validation folds (default: 5).

    Returns:
        String with job_id. Results will be saved in project_status.json
    """
    try:
        _check_inside(project_path)
    except ValueError as e:
        return str(e)
    job_id = str(uuid.uuid4())
    asyncio.create_task(asyncio.to_thread(
        train_model, job_id, project_path, key_features, explore_features,
        target, task_type, model_type, test_size, random_state, use_smote, cv_folds
    ))

    return f"Model train started. Job ID: {job_id}. Do not utilize other tools until the user asks"

@mcp.tool()
async def run_advanced_model_visualizations(project_path:str, status_job_id:str, rank:int = 1):
    """
    Generate advanced model performance visualizations (learning curves, confusion matrix,
    ROC-AUC, SHAP, etc.) for a specific ranked model from the training results.

    Args:
        project_path (str): Absolute project directory path
        status_job_id (str): job id that identify model (from train_model)
        rank (int): Which ranked model to visualize (1 = best, 2 = second best, ...). Default: 1

    Returns:
        String with job_id. results will be saved in project_status.json
    """
    try:
        _check_inside(project_path)
    except ValueError as e:
        return str(e)
    job_id = str(uuid.uuid4())
    asyncio.create_task(asyncio.to_thread(create_advanced_model_visualizations, job_id, project_path, status_job_id, rank))

    return f"Advanced model visualization started. Job ID: {job_id}. Do not utilize other tools until the user asks"

@mcp.tool()
async def run_importance_table_generation(project_path:str, status_job_id:str, rank:int = 1):
    """
    Generate feature importance table and visualization for a specific ranked model.

    Args:
        project_path (str): Absolute project directory path
        status_job_id (str): job id that identify model (from train_model)
        rank (int): Which ranked model to analyze (1 = best, 2 = second best, ...). Default: 1

    Returns:
        String with job_id. results will be saved in project_status.json
    """
    try:
        _check_inside(project_path)
    except ValueError as e:
        return str(e)
    job_id = str(uuid.uuid4())
    asyncio.create_task(asyncio.to_thread(generate_importance_table, job_id, project_path, status_job_id, rank))

    return f"Importance table generation started. Job ID: {job_id}. Do not utilize other tools until the user asks"



@mcp.tool()
async def get_project_status_for_ml(project_path:str, section:list):
    """
    Read project_status.json file within project_path and return sections. Use only when there is a user request.
    specified in section_list as key: value formatted string
    
    Args:
        project_path (str): Absolute project directory path
        section_list (List[str]): List of section names to read. section is one of [name, path, create_at, data_file, data_analysis, models, visualizations, features, feature_selection]
    Returns:
        str: Key: value formatted string
    """
    try:
        _check_inside(project_path)
    except ValueError as e:
        return str(e)
    project_status = await get_project_status(project_path=project_path, section=section)

    return project_status


@mcp.tool()
async def get_job_status_by_job_id_for_ml(job_id: str):
    """
    Retrieve job status by job_id from log database.
    Execute this tool ONLY when user explicitly requests to check job status.
    Do NOT call this tool repeatedly or automatically — call it once per user request.

    Args:
        job_id (str): Job ID to query

    Returns:
        str: Job status as JSON string, or error message if job not found
    """

    job_status = await get_job_status_by_id(job_id=job_id)
    return job_status

@mcp.tool()
async def get_latest_n_status_for_ml(n: int):
    """
    Retrieve the latest N job status rows from log database, ordered by updated_at.
    Execute this tool ONLY when user explicitly requests to check job status.
    Do NOT call this tool repeatedly or automatically — call it once per user request.

    Args:
        n (int): Number of latest job status rows to retrieve

    Returns:
        str: List of job status as JSON string
    """
    import json
    job_status_list = await get_latest_n_status(n=n)
    return json.dumps(job_status_list, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    logging.info("Starting PubMed MCP server")
    mcp.run(transport="streamable-http")
