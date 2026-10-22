from typing import  List
import logging
from mcp.server.fastmcp import FastMCP
from file_system import _check_inside, _find_files_by_partial_name, _read_file_content, _write_file_by_type
from pathlib import Path

# Set up logging
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Initialize FastMCP server
mcp = FastMCP(
    "File-system-tools",  # Name of the MCP server
    host="0.0.0.0",  # Host address (0.0.0.0 allows connections from any IP)
    # port=29501,  # Port number for the server
    stateless_http=True
)

# region file-system
# js로 구현되어있던 file-system tool을 그대로 python으로 변경한 코드이며, 불필요한 도구는 아직 미구현 상태
# 'text', 'json','csv','image' 등 /app/data 디렉토리 내 다양한 포맷의 데이터를 읽기, 쓰기, 찾기 구현
# dictionary 찾기 및 ls 구현
@mcp.tool()
def read_file(paths: List[str], partial: bool = True):
    '''
    Read the content of one or more files from the allowed directories.
    Args:
        paths: List of file paths to read. Each path must be inside one of the allowed root directories.
        partial: If True, returns only a portion of the file content.
    Returns:
        A single string containing the content of each file, separated by "---" if multiple files are read.
    '''
    roots = ['/app/data']
    blobs = []
    for raw in paths:
        try:
            p = _check_inside(Path(raw), roots)
            content = _read_file_content(p, partial)
            blobs.append(f"{raw}:\n{content}\n")
        except Exception as exc:  # noqa: BLE001
            blobs.append(f"{raw}: Error – {exc}")
    return "\n---\n".join(blobs)

@mcp.tool()
def search_files_by_pattern(file_path: str, substring: str, exclude_patterns: List[str]):
    """
    Search for files containing a specific substring in their name within the allowed directory.
    Args:
        file_path: Base directory path to search within. Must be inside one of the allowed root directories.
        substring: Substring to match in file names.
        exclude_patterns: List of patterns to exclude from search results.
    Returns:
        A string listing all matching file paths, one per line.
    """

    roots = ['/app/data']
    try:
        p = _check_inside(Path(file_path), roots)
        matches = _find_files_by_partial_name(p, substring, exclude_patterns)
        return "\n".join(matches) if matches else "No matches found"
    except:
        matches = _find_files_by_partial_name(roots, substring, exclude_patterns)
        return "\n".join(matches) if matches else "No matches found"


@mcp.tool()
def write_file(path: str, content: str, data_type: str = "text"):
    """
    Create or overwrite a file with the specified content and data type.
    Args:
        path: Absolute File path to write to. Must be inside "/app/data".
        content: The content to write to the file.
        data_type: Type of data to write. Must be one of ['text', 'json', 'csv', 'binary']. Defaults to 'text'.
    Returns:
        A success message if writing succeeds.
    """

    roots = ["/app/data"]
    try:
        p = _check_inside(Path(path), roots)
        _write_file_by_type(p, content, data_type)
        return f"Successfully wrote {data_type} data to {path}"
    except Exception as e:
        return f"Error writing file: {e}"

if __name__ == "__main__":
    logging.info("Starting PubMed MCP server")
    mcp.run(transport="streamable-http")