"""
Query Tools - Unified SQL query execution tools.
"""

import uuid
import asyncio
from typing import Optional, List

from mcp.server.fastmcp import FastMCP

from core.database_registry import DatabaseRegistry
from adapters import get_adapter
from export.csv_exporter import StreamingCSVExporter
from export.job_status_manager import create_job
from utils.path_validator import check_inside


def register_query_tools(mcp: FastMCP, registry: DatabaseRegistry):
    """
    Register query-related tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        registry: Database registry
    """

    @mcp.tool()
    def query(db: str, sql: str, parameters: Optional[List] = None) -> str:
        """
        Execute a SQL query against the specified database.

        Args:
            db (str): Database identifier. Available: cdm, kmimic, mimiciv, inspire, synthea
            sql (str): SQL query string to execute
            parameters (list, optional): Parameters for parameterized queries

        Returns:
            str: Formatted query results or error message
        """
        # Validate database
        db_config = registry.get_database(db)
        if not db_config:
            available = ", ".join(registry.list_databases())
            return f"Unknown database '{db}'. Available databases: {available}"

        try:
            adapter = get_adapter(db_config)
            executor = adapter.get_query_executor(
                default_limit=registry.get_setting('default_query_limit', 5)
            )
            return executor.execute_query(sql, parameters)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def query_to_csv(db: str, sql: str, path: str,
                     parameters: Optional[List] = None,
                     batch_size: int = 10000,
                     max_file_size_mb: int = 1024) -> str:
        """
        Execute a SQL query and save results to CSV file with streaming.

        Args:
            db (str): Database identifier. Available: cdm, kmimic, mimiciv, inspire, synthea
            sql (str): SQL query string to execute
            path (str): Output file path (must be under /app/data)
            parameters (list, optional): Parameters for parameterized queries
            batch_size (int): Rows per batch for streaming (default: 10000)
            max_file_size_mb (int): Max file size before splitting (default: 1024)

        Returns:
            str: Job ID for tracking progress
        """
        # Validate database
        db_config = registry.get_database(db)
        if not db_config:
            available = ", ".join(registry.list_databases())
            return f"Unknown database '{db}'. Available databases: {available}"

        # Validate path
        try:
            check_inside(path, db_config.data_output_root)
        except ValueError as e:
            return str(e)

        # Generate job ID
        job_id = str(uuid.uuid4())

        try:
            adapter = get_adapter(db_config)

            # Create exporter with factory function
            def query_executor_factory():
                return adapter.get_query_executor()

            exporter = StreamingCSVExporter(
                query_executor_factory,
                default_batch_size=registry.get_default_batch_size(),
                default_max_file_size_mb=registry.get_max_file_size_mb()
            )

            # Run export in background
            asyncio.create_task(asyncio.to_thread(
                exporter.export,
                job_id=job_id,
                sql=sql,
                path=path,
                parameters=parameters,
                batch_size=batch_size,
                max_file_size_mb=max_file_size_mb
            ))

            return f"Query execution started. Job ID: {job_id}. Use get_job_status(job_id) to track progress."

        except Exception as e:
            return f"Error starting export: {str(e)}"
