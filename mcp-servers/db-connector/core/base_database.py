"""
Base Database Adapter - Abstract base class for database-specific implementations.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

from .database_registry import DatabaseEntry
from .query_executor import QueryExecutor


class BaseDatabaseAdapter(ABC):
    """
    Abstract base class for database-specific adapters.
    Provides common interface for all database operations.
    """

    def __init__(self, config: DatabaseEntry):
        """
        Initialize adapter with database configuration.

        Args:
            config: Database configuration entry
        """
        self.config = config
        self._query_executor = None
        self._metadata = None

    @property
    def db_id(self) -> str:
        """Get database identifier."""
        return self.config.db_id

    @property
    def schemas(self) -> List[str]:
        """Get available schemas."""
        return self.config.schemas

    def get_query_executor(self, default_limit: int = 5) -> QueryExecutor:
        """
        Get or create query executor.

        Args:
            default_limit: Default row limit for queries

        Returns:
            QueryExecutor instance
        """
        if self._query_executor is None:
            self._query_executor = QueryExecutor(
                self.config.connection_url,
                default_limit
            )
        return self._query_executor

    def validate_schema(self, schema_name: str) -> bool:
        """
        Validate if schema exists in this database.

        Args:
            schema_name: Schema to validate

        Returns:
            True if schema is valid
        """
        return schema_name in self.schemas

    def get_default_schema(self) -> Optional[str]:
        """
        Get default schema for single-schema databases.

        Returns:
            Default schema name or None if multiple schemas
        """
        if len(self.schemas) == 1:
            return self.schemas[0]
        return None

    @abstractmethod
    def load_metadata(self) -> Dict[str, Any]:
        """
        Load and return metadata from Information.json.

        Returns:
            Metadata dictionary
        """
        pass

    # Optional hook methods for database-specific features
    def concept_id_to_name(self, concept_ids: List[int]) -> Dict[int, str]:
        """
        Convert concept IDs to names.
        Override in CDM adapter.

        Args:
            concept_ids: List of concept IDs

        Returns:
            Dictionary mapping ID to name
        """
        return {}

    def get_guide(self, guide_type: str) -> Optional[str]:
        """
        Get research guide content.
        Override in CDM adapter.

        Args:
            guide_type: Type of guide (cohort, statistic, visualization)

        Returns:
            Guide content or None
        """
        return None

    def has_feature(self, feature_name: str) -> bool:
        """
        Check if database has a specific feature.

        Args:
            feature_name: Feature to check

        Returns:
            True if feature is enabled
        """
        return self.config.has_feature(feature_name)
