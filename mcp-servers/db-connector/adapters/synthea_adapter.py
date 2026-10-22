"""
Synthea Adapter - Synthea Synthetic Patient Database specific implementation.
"""

import json
from typing import Dict, Any, List
from pathlib import Path

from core.base_database import BaseDatabaseAdapter
from core.database_registry import DatabaseEntry


class SyntheaAdapter(BaseDatabaseAdapter):
    """
    Adapter for Synthea Synthetic Patient Database.
    Contains synthetic patient records including allergies, conditions,
    encounters, medications, observations, procedures, and more.
    """

    def __init__(self, config: DatabaseEntry):
        super().__init__(config)

    def load_metadata(self) -> Dict[str, Any]:
        """Load Synthea metadata from Information.json."""
        if self._metadata is not None:
            return self._metadata

        metadata_path = self._get_documents_path() / "Information.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"Synthea metadata not found: {metadata_path}")

        with open(metadata_path, 'r', encoding='utf-8') as f:
            self._metadata = json.load(f)

        return self._metadata

    def _get_documents_path(self) -> Path:
        """Get path to documents directory."""
        possible_paths = [
            Path("/app/mcp-servers/documents/synthea"),
            Path(__file__).parent.parent / "documents" / "synthea",
        ]
        for path in possible_paths:
            if path.exists():
                return path

        return possible_paths[0]

    def get_tables_for_schemas(self, schema_names: List[str]) -> Dict[str, List[str]]:
        """
        Get table names for multiple schemas.

        Args:
            schema_names: List of schema names

        Returns:
            Dictionary mapping schema to table list
        """
        metadata = self.load_metadata()
        result = {}

        for schema in schema_names:
            if schema in metadata:
                result[schema] = list(metadata[schema].get('Tables', {}).keys())
            else:
                result[schema] = []

        return result
