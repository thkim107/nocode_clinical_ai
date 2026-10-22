"""
Job Tools - Job status tracking tools for async operations.
"""

import json
from mcp.server.fastmcp import FastMCP

from export.job_status_manager import get_job_status_by_id, get_latest_n_status


def register_job_tools(mcp: FastMCP):
    """
    Register job status tools with the MCP server.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.tool()
    async def get_job_status(job_id: str) -> str:
        """
        Get the status of a job by its ID.

        Args:
            job_id (str): The job ID returned from query_to_csv

        Returns:
            str: JSON formatted job status
        """
        try:
            status = await get_job_status_by_id(job_id)

            if status is None:
                return f"Job not found: {job_id}"

            # Format for readability
            return json.dumps(status, indent=2, ensure_ascii=False)

        except Exception as e:
            return f"Error getting job status: {str(e)}"

    @mcp.tool()
    async def get_latest_jobs(n: int = 10) -> str:
        """
        Get the latest N job statuses.

        Args:
            n (int): Number of jobs to retrieve (default: 10)

        Returns:
            str: JSON formatted list of job statuses
        """
        try:
            statuses = await get_latest_n_status(n)

            if not statuses:
                return "No jobs found"

            # Format for readability
            return json.dumps(statuses, indent=2, ensure_ascii=False)

        except Exception as e:
            return f"Error getting job statuses: {str(e)}"
