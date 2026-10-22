import os
from datetime import datetime
from pathlib import Path
import json

def ensure_dir(directory):
    """Create directory if it doesn't exist."""
    if not os.path.exists(directory):
        os.makedirs(directory)

def _check_inside(candidate: str) -> Path:
    """Ensure *candidate* is a child of *roots* (string‑prefix test) and exists."""
    root = "/app/data"
    candidate = Path(candidate)
    resolved = candidate.expanduser().resolve()
    
    if not str(resolved).startswith(str(root)):
        raise ValueError(
            "Access denied – {} outside allowed root: {}".format(resolved, root)
        )
    
    if not resolved.exists():
        raise ValueError(
            "Path does not exist: {}".format(resolved)
        )
    
    return resolved

def save_project_status(path: str, status: dict) -> None:
    """Save project status to JSON file."""
    status["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_file = os.path.join(path, "project_status.json")
    with open(status_file, 'w') as f:
        json.dump(status, f, indent=4)


def read_project_status(path: str) -> dict:
    """Read project status from JSON file or create a new one if it doesn't exist."""
    status_file = os.path.join(path, "project_status.json")
    if os.path.exists(status_file):
        with open(status_file, 'r') as f:
            return json.load(f)
    else:
        # Create default project status
        default_status = {
            "project_path": path,
            "data_file": None,
            "data_analysis": None,
            "features": [],
            "target": None,
            "models": {},
            "model_parameters": {},
            "model_type": None,
            "results": {},
            "visualizations": {},
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        return default_status

async def create_project(name: str) -> str:
    """
    Create a new machine learning project with the specified name at the given local path.
    If no path is provided, the default path is "/app/data".
    
    Args:
        path: Local directory path where the project will be created. 
    
    Returns:
        String with project creation status
    """
    # default path
    path = "/app/data"

    # Create project directory structure
    project_path = os.path.join(path, name)
    ensure_dir(project_path)
    sub_paths = ["data", "models", "results", "visualizations", "reports"]
    for sub_path in sub_paths:
        ensure_dir(os.path.join(project_path, sub_path))

    # Initialize project status
    project_status = {
        "name": name,
        "path": project_path,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_file": None,
        "data_analysis": None,        
        "models": {},
        "model_parameters": {
            "features": [],
            "target": None,
            "model_type": None,
        },        
        "results": {},
        "visualizations": {},
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Save project status
    save_project_status(project_path, project_status)
    
    return f"Project '{name}' created successfully at {project_path}. Directory structure initialized with visualizations and reports folders."


async def get_project_status(project_path:str, section:list) -> str:
    """
    Read project_status.json file within project_path and return sections 
    specified in section_list as key: value formatted string
    
    Args:
        project_path (str): Project directory path
        section_list (List[str]): List of section names to read
    
    Returns:
        str: Key: value formatted string
    """
    try:
        # project_status.json 파일 경로 구성
        status_file_path = os.path.join(project_path, 'project_status.json')
        
        # 파일 존재 여부 확인
        if not os.path.exists(status_file_path):
            return f"Error: project_status.json not found in {project_path}"
        
        # JSON 파일 읽기
        with open(status_file_path, 'r', encoding='utf-8') as file:
            status_data = json.load(file)
        
        # 결과 문자열 구성
        result_lines = []
        
        for section in section:
            if section in status_data:
                value = status_data[section]
                
                # 값이 딕셔너리인 경우 JSON 형태로 표시
                if isinstance(value, dict):
                    value_str = json.dumps(value, ensure_ascii=False, indent=2)
                # 값이 리스트인 경우 문자열로 변환
                elif isinstance(value, list):
                    value_str = str(value)
                # 기타 값들은 문자열로 변환
                else:
                    value_str = str(value)
                
                result_lines.append(f"{section}: {value_str}")
            else:
                result_lines.append(f"{section}: (섹션을 찾을 수 없음)")
        
        return '\n'.join(result_lines)
    
    except json.JSONDecodeError as e:
        return f"Error: JSON 파일 파싱 실패 - {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"