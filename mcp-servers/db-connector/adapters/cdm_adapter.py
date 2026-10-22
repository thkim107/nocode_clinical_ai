"""
CDM Adapter - OMOP Common Data Model specific implementation.
"""

import json
from typing import Dict, Any, List, Optional
from pathlib import Path

from core.base_database import BaseDatabaseAdapter
from core.database_registry import DatabaseEntry


class CDMAdapter(BaseDatabaseAdapter):
    """
    Adapter for OMOP CDM database.
    Includes concept mapping and research guides features.
    """

    def __init__(self, config: DatabaseEntry):
        super().__init__(config)
        self._concept_mapping = None
        self._guides_path = None

    def load_metadata(self) -> Dict[str, Any]:
        """Load CDM metadata from Information.json."""
        if self._metadata is not None:
            return self._metadata

        metadata_path = self._get_documents_path() / "Information.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"CDM metadata not found: {metadata_path}")

        with open(metadata_path, 'r', encoding='utf-8') as f:
            self._metadata = json.load(f)

        return self._metadata

    def _get_documents_path(self) -> Path:
        """Get path to documents directory."""
        # Try multiple possible locations
        possible_paths = [
            Path("/app/mcp-servers/documents/cdm"),
            Path(__file__).parent.parent / "documents" / "cdm",
        ]
        for path in possible_paths:
            if path.exists():
                return path

        # Return default path even if not exists
        return possible_paths[0]

    def _load_concept_mapping(self) -> Dict[str, Any]:
        """Load HIRA concept mapping from JSON."""
        if self._concept_mapping is not None:
            return self._concept_mapping

        mapping_path = self._get_documents_path() / "ConceptMapping.json"
        if not mapping_path.exists():
            # Fallback: concept mapping not available
            self._concept_mapping = {}
            return self._concept_mapping

        with open(mapping_path, 'r', encoding='utf-8') as f:
            self._concept_mapping = json.load(f)

        return self._concept_mapping

    def concept_id_to_name(self, concept_ids: List[int]) -> Dict[int, str]:
        """
        Convert HIRA concept IDs to names.

        Args:
            concept_ids: List of concept IDs

        Returns:
            Dictionary mapping ID to name
        """
        mapping = self._load_concept_mapping()
        result = {}

        for concept_id in concept_ids:
            str_id = str(concept_id)
            if str_id in mapping:
                names = mapping[str_id].get('names', [])
                if names:
                    result[concept_id] = names[0]  # Return first name
                else:
                    result[concept_id] = f"Unknown ({concept_id})"
            else:
                result[concept_id] = f"Unknown ({concept_id})"

        return result

    def get_guide(self, guide_type: str) -> Optional[str]:
        """
        Get research guide content.

        Args:
            guide_type: 'cohort', 'statistic', or 'visualization'

        Returns:
            Guide content or None
        """
        valid_types = ['cohort', 'statistic', 'visualization']
        if guide_type not in valid_types:
            return None

        guide_files = {
            'cohort': 'omop_cohort_guide.txt',
            'statistic': 'omop_statistic_guide.txt',
            'visualization': 'omop_visualization_guide.txt'
        }

        guide_path = self._get_documents_path() / "guides" / guide_files[guide_type]

        # Also try without 'guides' subdirectory for backward compatibility
        if not guide_path.exists():
            guide_path = self._get_documents_path() / guide_files[guide_type]

        if not guide_path.exists():
            return None

        with open(guide_path, 'r', encoding='utf-8') as f:
            return f.read()
