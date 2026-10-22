"""
Metadata Tools - Database schema and structure information tools.
"""

from typing import Optional, List
import json

from mcp.server.fastmcp import FastMCP

from core.database_registry import DatabaseRegistry
from core.metadata_manager import MetadataManager
from adapters import get_adapter


def register_metadata_tools(mcp: FastMCP, registry: DatabaseRegistry,
                            metadata_manager: MetadataManager):
    """
    Register metadata-related tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        registry: Database registry
        metadata_manager: Metadata manager instance
    """

    @mcp.tool()
    def get_names(db: str, mode: str, schema_name: Optional[str] = None) -> str:
        """
        Retrieve table or field names from the specified database.

        Args:
            db (str): Database identifier (cdm, kmimic, mimiciv, inspire, synthea)
            mode (str): 'table' for table names, 'field' for field names
            schema_name (str, optional): Filter by schema.
                Each database has its own schema names (NOT always 'public'):
                - synthea: 'synthea'
                - mimiciv: 'mimiciv_hosp', 'mimiciv_icu'
                - kmimic: 'kmimic'
                - inspire: 'inspire'
                - cdm: 'cdm'
                If omitted or invalid, the default schema for the database is used automatically.

        Returns:
            str: Formatted list of names
        """
        db_config = registry.get_database(db)
        if not db_config:
            available = ", ".join(registry.list_databases())
            return f"Unknown database '{db}'. Available: {available}"

        try:
            adapter = get_adapter(db_config)
            metadata = adapter.load_metadata()

            # Auto-resolve invalid schema
            correction_note = ""
            if schema_name:
                resolved = registry.resolve_schema(db, schema_name)
                if resolved and resolved != schema_name:
                    correction_note = f"[NOTE] schema '{schema_name}' is invalid for '{db}'. Auto-corrected to '{resolved}'. Use '{resolved}' for subsequent calls.\n\n"
                    schema_name = resolved

            # For single-schema databases, use the default schema
            if not schema_name:
                default_schema = adapter.get_default_schema()
                if default_schema:
                    schema_name = default_schema

            if mode == 'table':
                if schema_name:
                    tables = metadata_manager.get_table_names(metadata, schema_name)
                    return f"{correction_note}# Tables in {schema_name}\n{tables}"
                else:
                    result = "# Tables\n"
                    for schema in db_config.schemas:
                        tables = metadata_manager.get_table_names(metadata, schema)
                        result += f"## {schema}: {tables}\n"
                    return result

            elif mode == 'field':
                if not schema_name:
                    return "schema_name is required for field mode in multi-schema databases"

                result = f"{correction_note}# Fields in {schema_name}\n"
                for table in metadata_manager.get_table_names(metadata, schema_name):
                    fields = metadata_manager.get_field_names(metadata, schema_name, table)
                    result += f"## {table}: {fields}\n"
                return result

            return f"Invalid mode '{mode}'. Use 'table' or 'field'."

        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def get_keys(db: str, schema_name: str, table_name: str) -> str:
        """
        Get Primary Key and Foreign Key information for a table.

        Args:
            db (str): Database identifier (cdm, kmimic, mimiciv, inspire, synthea)
            schema_name (str): Schema name. Use the database-specific schema
                (e.g. 'synthea' for synthea, 'mimiciv_hosp'/'mimiciv_icu' for mimiciv).
                Auto-corrected to the default schema if invalid.
            table_name (str): Table name

        Returns:
            str: Formatted PK/FK information
        """
        db_config = registry.get_database(db)
        if not db_config:
            return f"Unknown database '{db}'"

        correction_note = ""
        resolved = registry.resolve_schema(db, schema_name)
        if resolved and resolved != schema_name:
            correction_note = f"[NOTE] schema '{schema_name}' is invalid for '{db}'. Auto-corrected to '{resolved}'. Use '{resolved}' for subsequent calls.\n\n"
            schema_name = resolved

        try:
            adapter = get_adapter(db_config)
            metadata = adapter.load_metadata()
            keys = metadata_manager.get_keys(metadata, schema_name, table_name)

            result = f"{correction_note}# {schema_name}.{table_name}\n"

            if keys['primary_keys']:
                result += f"## Primary Keys: {', '.join(keys['primary_keys'])}\n"

            if keys['foreign_keys']:
                result += "## Foreign Keys:\n"
                for fk in keys['foreign_keys']:
                    result += f"  - {fk['field']} -> {fk['references']}\n"

            if not keys['primary_keys'] and not keys['foreign_keys']:
                result += "## No Primary Key or Foreign Key defined\n"

            return result

        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def get_relations(db: str, schema_name: str) -> str:
        """
        Get all foreign key relations in a schema.

        Args:
            db (str): Database identifier (cdm, kmimic, mimiciv, inspire, synthea)
            schema_name (str): Schema name. Use the database-specific schema
                (e.g. 'synthea' for synthea, 'mimiciv_hosp'/'mimiciv_icu' for mimiciv).
                Auto-corrected to the default schema if invalid.

        Returns:
            str: Formatted relation information
        """
        db_config = registry.get_database(db)
        if not db_config:
            return f"Unknown database '{db}'"

        correction_note = ""
        resolved = registry.resolve_schema(db, schema_name)
        if resolved and resolved != schema_name:
            correction_note = f"[NOTE] schema '{schema_name}' is invalid for '{db}'. Auto-corrected to '{resolved}'. Use '{resolved}' for subsequent calls.\n\n"
            schema_name = resolved

        try:
            adapter = get_adapter(db_config)
            metadata = adapter.load_metadata()
            relations = metadata_manager.get_relations(metadata, schema_name)

            if not relations:
                return f"{correction_note}No relations found in {schema_name}"

            result = f"{correction_note}# Relations in {schema_name}\n"
            for rel in relations:
                result += f"{rel['source']} -> {rel['target']}\n"
            return result

        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def get_descriptions(db: str, level: str, schema_name: str,
                         table_name: Optional[str] = None) -> str:
        """
        Retrieve descriptions at schema, table, or field level.

        Args:
            db (str): Database identifier (cdm, kmimic, mimiciv, inspire, synthea)
            level (str): 'schema', 'table', or 'field'
            schema_name (str): Schema name. Use the database-specific schema
                (e.g. 'synthea' for synthea, 'mimiciv_hosp'/'mimiciv_icu' for mimiciv).
                Auto-corrected to the default schema if invalid.
            table_name (str, optional): Table name (required for table/field level)

        Returns:
            str: Formatted descriptions
        """
        db_config = registry.get_database(db)
        if not db_config:
            return f"Unknown database '{db}'"

        correction_note = ""
        resolved = registry.resolve_schema(db, schema_name)
        if resolved and resolved != schema_name:
            correction_note = f"[NOTE] schema '{schema_name}' is invalid for '{db}'. Auto-corrected to '{resolved}'. Use '{resolved}' for subsequent calls.\n\n"
            schema_name = resolved

        try:
            adapter = get_adapter(db_config)
            metadata = adapter.load_metadata()

            if level == 'schema':
                desc = metadata_manager.get_schema_description(metadata, schema_name)
                return f"{correction_note}# {schema_name}\n{desc}"

            elif level == 'table':
                if not table_name:
                    return "table_name is required for table-level descriptions"
                desc = metadata_manager.get_table_description(metadata, schema_name, table_name)
                return f"{correction_note}# {schema_name}.{table_name}\n{desc}"

            elif level == 'field':
                if not table_name:
                    return "table_name is required for field-level descriptions"
                fields = metadata_manager.get_field_info(metadata, schema_name, table_name, 'descriptive')
                result = f"{correction_note}# Fields in {schema_name}.{table_name}\n"
                for name, info in fields.items():
                    desc = info.get('description', 'No description')
                    result += f"## {name}: {desc}\n"
                return result

            return f"Invalid level '{level}'. Use 'schema', 'table', or 'field'."

        except Exception as e:
            return f"Error: {str(e)}"

    # CDM-specific tools
    @mcp.tool()
    def concept_id_to_name(concept_ids: List[int]) -> str:
        """
        Convert HIRA concept IDs to names (CDM only).

        Args:
            concept_ids (list[int]): List of concept IDs to convert

        Returns:
            str: Formatted concept ID to name mappings
        """
        db_config = registry.get_database('cdm')
        if not db_config:
            return "CDM database not configured"

        if not db_config.has_feature('concept_mapping'):
            return "Concept mapping feature not enabled for CDM"

        try:
            adapter = get_adapter(db_config)
            mappings = adapter.concept_id_to_name(concept_ids)

            result = "# Concept ID Mappings\n"
            for concept_id, name in mappings.items():
                result += f"{concept_id}: {name}\n"
            return result

        except Exception as e:
            return f"Error: {str(e)}"

    # Common research guides (available for all databases)
    @mcp.tool()
    def get_research_guide(guide_type: str) -> str:
        """
        Get clinical research guide.

        Available guides:
        - cohort: Cohort definition and analysis methodology
        - statistic: Statistical analysis methods for clinical research
        - visualization: Data visualization best practices

        Args:
            guide_type (str): Type of guide - 'cohort', 'statistic', or 'visualization'

        Returns:
            str: Guide content
        """
        from pathlib import Path

        valid_types = ['cohort', 'statistic', 'visualization']
        if guide_type not in valid_types:
            return f"Invalid guide type '{guide_type}'. Available: {', '.join(valid_types)}"

        guide_files = {
            'cohort': 'cohort_guide.txt',
            'statistic': 'statistic_guide.txt',
            'visualization': 'visualization_guide.txt'
        }

        # Try multiple possible locations
        possible_paths = [
            Path("/app/mcp-servers/documents/guides"),
            Path(__file__).parent.parent / "documents" / "guides",
        ]

        for base_path in possible_paths:
            guide_path = base_path / guide_files[guide_type]
            if guide_path.exists():
                try:
                    with open(guide_path, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception as e:
                    return f"Error reading guide: {str(e)}"

        return f"Guide file not found: {guide_files[guide_type]}"
