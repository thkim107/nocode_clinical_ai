"""
KMIMIC Adapter - Korean MIMIC database specific implementation.
"""

import json
from typing import Dict, Any
from pathlib import Path

from core.base_database import BaseDatabaseAdapter
from core.database_registry import DatabaseEntry


class KMIMICAdapter(BaseDatabaseAdapter):
    """
    Adapter for Korean MIMIC database.
    Supports three hospital schemas: km001, km006, km012.
    """

    def __init__(self, config: DatabaseEntry):
        super().__init__(config)

    def load_metadata(self) -> Dict[str, Any]:
        """Load KMIMIC metadata from Information.json."""
        if self._metadata is not None:
            return self._metadata

        metadata_path = self._get_documents_path() / "Information.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"KMIMIC metadata not found: {metadata_path}")

        with open(metadata_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # KMIMIC JSON structure has 'kmimic' as top-level key
        # We need to restructure to have schema names as top-level keys
        if 'kmimic' in data:
            # All schemas share the same table structure
            kmimic_data = data['kmimic']
            self._metadata = {}
            for schema in self.schemas:
                self._metadata[schema] = {
                    'Description': f"{kmimic_data.get('Description', '')} (Schema: {schema})",
                    'Tables': kmimic_data.get('Tables', {})
                }
        else:
            self._metadata = data

        return self._metadata

    def _get_documents_path(self) -> Path:
        """Get path to documents directory."""
        possible_paths = [
            Path("/app/mcp-servers/documents/kmimic"),
            Path(__file__).parent.parent / "documents" / "kmimic",
        ]
        for path in possible_paths:
            if path.exists():
                return path

        return possible_paths[0]

    def validate_schema(self, schema_name: str) -> bool:
        """
        Validate KMIMIC schema with explicit list.

        Args:
            schema_name: Schema to validate

        Returns:
            True if valid, raises ValueError otherwise
        """
        if schema_name not in self.schemas:
            raise ValueError(
                f"Invalid schema '{schema_name}'. "
                f"Available schemas: {', '.join(self.schemas)}"
            )
        return True
