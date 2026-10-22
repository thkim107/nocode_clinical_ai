"""
Unified Database MCP Service - Main Entry Point

A unified MCP server for querying multiple clinical databases:
- CDM (OMOP Common Data Model with HIRA data)
- KMIMIC (Korean MIMIC - Multi-center ICU database)
- MIMICIV (MIMIC-IV Clinical Database)
"""

import os
import sys
from pathlib import Path

# Add the service directory to Python path
SERVICE_DIR = Path(__file__).parent
sys.path.insert(0, str(SERVICE_DIR))

from mcp.server.fastmcp import FastMCP

from core.database_registry import DatabaseRegistry
from core.metadata_manager import MetadataManager
from export.job_status_manager import JobStatusManager
from utils.init_database import init_job_status_db
from tools.query_tools import register_query_tools
from tools.metadata_tools import register_metadata_tools
from tools.job_tools import register_job_tools


def create_server() -> FastMCP:
    """
    Create and configure the MCP server.

    Returns:
        Configured FastMCP server instance
    """
    # Initialize MCP server
    mcp = FastMCP(
        "unified-db-tools",
        host="0.0.0.0",
        stateless_http=True
    )

    # Determine config path
    config_path = os.environ.get(
        'DB_CONFIG_PATH',
        str(SERVICE_DIR / 'config' / 'databases.yaml')
    )

    # Initialize components
    registry = DatabaseRegistry(config_path)

    # Set job status DB path
    job_db_path = registry.get_job_status_db_path()
    JobStatusManager.set_db_path(job_db_path)

    # Initialize job status database
    init_job_status_db(job_db_path)

    # Determine metadata base path
    metadata_base_path = os.environ.get(
        'METADATA_BASE_PATH',
        '/app/mcp-servers'
    )

    # If running locally, use local documents path
    local_docs = SERVICE_DIR / 'documents'
    if local_docs.exists():
        metadata_base_path = str(SERVICE_DIR)

    metadata_manager = MetadataManager(metadata_base_path)

    # Register tools
    register_query_tools(mcp, registry)
    register_metadata_tools(mcp, registry, metadata_manager)
    register_job_tools(mcp)

    def _check_database_connection(connection_url: str) -> bool:
        """
        Check if database is accessible by running SELECT 1.

        Args:
            connection_url: Database connection URL

        Returns:
            True if connection successful, False otherwise
        """
        if not connection_url:
            return False

        import psycopg2
        try:
            conn = psycopg2.connect(connection_url)
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.close()
            return True
        except Exception:
            return False

    # Add server info tool
    @mcp.tool()
    def list_databases() -> str:
        """
        List all available databases and their schemas.
        Only shows databases with valid connection URLs that are accessible.

        Returns:
            str: Formatted list of databases and schemas
        """
        result = "# Available Databases\n\n"
        available_count = 0

        for db_id in registry.list_databases():
            db_config = registry.get_database(db_id)
            if db_config:
                # Skip if no connection URL configured
                if not db_config.connection_url:
                    continue

                # Skip if database is not accessible
                if not _check_database_connection(db_config.connection_url):
                    continue

                available_count += 1
                result += f"## {db_id} ({db_config.display_name})\n"
                result += f"Description: {db_config.description}\n"
                result += f"Schemas: {', '.join(db_config.schemas)}\n"

                features = []
                if db_config.has_feature('concept_mapping'):
                    features.append('concept_mapping')
                if db_config.has_feature('research_guides'):
                    features.append('research_guides')
                if features:
                    result += f"Features: {', '.join(features)}\n"

                result += "\n"

        if available_count == 0:
            result += "No databases are currently available.\n"

        return result

    return mcp


# Create server instance
mcp = create_server()

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
