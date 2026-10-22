"""
Metadata Manager - Unified JSON metadata loading and querying.
"""

import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from functools import lru_cache


class MetadataManager:
    """
    Unified metadata management using JSON format.
    Provides caching and query methods for database schema information.
    """

    def __init__(self, metadata_base_path: str):
        """
        Initialize metadata manager.

        Args:
            metadata_base_path: Base directory containing metadata files
        """
        self.base_path = Path(metadata_base_path)
        self._cache: Dict[str, Dict[str, Any]] = {}

    def load_metadata(self, db_id: str, metadata_path: str) -> Dict[str, Any]:
        """
        Load metadata for a specific database.

        Args:
            db_id: Database identifier
            metadata_path: Relative path to Information.json

        Returns:
            Loaded metadata dictionary
        """
        if db_id in self._cache:
            return self._cache[db_id]

        full_path = self.base_path / metadata_path
        if not full_path.exists():
            raise FileNotFoundError(f"Metadata not found: {full_path}")

        with open(full_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self._cache[db_id] = data
        return data

    def clear_cache(self, db_id: Optional[str] = None):
        """
        Clear metadata cache.

        Args:
            db_id: Optional specific database to clear, or all if None
        """
        if db_id:
            self._cache.pop(db_id, None)
        else:
            self._cache.clear()

    def get_schema_description(self, metadata: Dict[str, Any], schema_name: str) -> str:
        """
        Get schema-level description.

        Args:
            metadata: Loaded metadata dictionary
            schema_name: Schema name

        Returns:
            Schema description string
        """
        return metadata.get(schema_name, {}).get('Description', '')

    def get_table_names(self, metadata: Dict[str, Any],
                        schema_name: Optional[str] = None) -> List[str]:
        """
        Get all table names.

        Args:
            metadata: Loaded metadata dictionary
            schema_name: Optional schema filter

        Returns:
            List of table names
        """
        if schema_name:
            return list(metadata.get(schema_name, {}).get('Tables', {}).keys())

        # Return tables from all schemas
        tables = []
        for schema_data in metadata.values():
            if isinstance(schema_data, dict) and 'Tables' in schema_data:
                tables.extend(schema_data['Tables'].keys())
        return tables

    def get_field_names(self, metadata: Dict[str, Any],
                        schema_name: str, table_name: str) -> List[str]:
        """
        Get field names for a specific table.

        Args:
            metadata: Loaded metadata dictionary
            schema_name: Schema name
            table_name: Table name

        Returns:
            List of field names
        """
        fields = metadata.get(schema_name, {}).get('Tables', {}).get(table_name, {}).get('Fields', {})
        return list(fields.keys())

    def get_table_description(self, metadata: Dict[str, Any],
                              schema_name: str, table_name: str) -> str:
        """
        Get table description.

        Args:
            metadata: Loaded metadata dictionary
            schema_name: Schema name
            table_name: Table name

        Returns:
            Table description string
        """
        return metadata.get(schema_name, {}).get('Tables', {}).get(table_name, {}).get('Description', '')

    def get_field_info(self, metadata: Dict[str, Any], schema_name: str,
                       table_name: str, info_type: str = 'all') -> Dict[str, Any]:
        """
        Get field information with filtering by info_type.

        Args:
            metadata: Loaded metadata dictionary
            schema_name: Schema name
            table_name: Table name
            info_type: 'all', 'descriptive', or 'relation'

        Returns:
            Dictionary of field information
        """
        fields = metadata.get(schema_name, {}).get('Tables', {}).get(table_name, {}).get('Fields', {})

        if info_type == 'all':
            return fields
        elif info_type == 'descriptive':
            return {
                name: {'description': info.get('description', '')}
                for name, info in fields.items()
            }
        elif info_type == 'relation':
            return {
                name: {
                    'is_pk': info.get('is_pk', False),
                    'is_fk': info.get('is_fk', False),
                    'relation': info.get('relation', '')
                }
                for name, info in fields.items()
            }
        return fields

    def get_relations(self, metadata: Dict[str, Any], schema_name: str) -> List[Dict[str, str]]:
        """
        Get all foreign key relations for a schema.

        Args:
            metadata: Loaded metadata dictionary
            schema_name: Schema name

        Returns:
            List of relation dictionaries
        """
        relations = []

        tables = metadata.get(schema_name, {}).get('Tables', {})
        for table_name, table_info in tables.items():
            for field_name, field_info in table_info.get('Fields', {}).items():
                if field_info.get('relation'):
                    relations.append({
                        'source': f"{schema_name}.{table_name}.{field_name}",
                        'target': field_info['relation']
                    })
        return relations

    def get_keys(self, metadata: Dict[str, Any],
                 schema_name: str, table_name: str) -> Dict[str, List[str]]:
        """
        Get primary and foreign keys for a table.

        Args:
            metadata: Loaded metadata dictionary
            schema_name: Schema name
            table_name: Table name

        Returns:
            Dictionary with 'primary_keys' and 'foreign_keys' lists
        """
        fields = metadata.get(schema_name, {}).get('Tables', {}).get(table_name, {}).get('Fields', {})

        primary_keys = []
        foreign_keys = []

        for field_name, field_info in fields.items():
            if field_info.get('is_pk', False):
                primary_keys.append(field_name)
            if field_info.get('is_fk', False):
                foreign_keys.append({
                    'field': field_name,
                    'references': field_info.get('relation', '')
                })

        return {
            'primary_keys': primary_keys,
            'foreign_keys': foreign_keys
        }
