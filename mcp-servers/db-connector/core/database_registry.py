"""
Database Registry - YAML-based database configuration management.
"""

import os
import yaml
from typing import Dict, Optional, List, Any
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class DatabaseEntry:
    """Represents a registered database configuration."""
    db_id: str
    display_name: str
    description: str
    connection_url: str
    schemas: List[str]
    metadata_path: str
    data_output_root: str
    features: Dict[str, bool] = field(default_factory=dict)

    def has_feature(self, feature_name: str) -> bool:
        """Check if database has a specific feature enabled."""
        return self.features.get(feature_name, False)


class DatabaseRegistry:
    """
    Singleton registry for managing database configurations.
    Loads configuration from YAML file and provides database lookup.
    """

    _instance = None

    def __new__(cls, config_path: Optional[str] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        if self._initialized:
            return

        # Determine config path
        if config_path:
            self._config_path = config_path
        else:
            # Default paths to check
            default_paths = [
                os.environ.get('DB_CONFIG_PATH'),
                '/app/mcp-servers/config/databases.yaml',
                Path(__file__).parent.parent / 'config' / 'databases.yaml'
            ]
            for path in default_paths:
                if path and Path(path).exists():
                    self._config_path = str(path)
                    break
            else:
                raise FileNotFoundError("Database configuration file not found")

        self._databases: Dict[str, DatabaseEntry] = {}
        self._settings: Dict[str, Any] = {}
        self._load_config()
        self._initialized = True

    def _load_config(self):
        """Load database configuration from YAML file."""
        with open(self._config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # Load database entries
        for db_id, db_config in config.get('databases', {}).items():
            # Resolve connection URL from environment variable
            env_var = db_config.get('connection_env', f'{db_id.upper()}_DATABASE_URL')
            connection_url = os.environ.get(env_var, '')

            self._databases[db_id] = DatabaseEntry(
                db_id=db_id,
                display_name=db_config.get('display_name', db_id),
                description=db_config.get('description', ''),
                connection_url=connection_url,
                schemas=db_config.get('schemas', []),
                metadata_path=db_config.get('metadata_path', ''),
                data_output_root=db_config.get(
                    'data_output_root',
                    os.environ.get('DATA_OUTPUT_ROOT', '/app/data')
                ),
                features=db_config.get('features', {})
            )

        # Load global settings
        self._settings = config.get('settings', {})

    def get_database(self, db_id: str) -> Optional[DatabaseEntry]:
        """Get database configuration by ID."""
        return self._databases.get(db_id)

    def list_databases(self) -> List[str]:
        """List all registered database IDs."""
        return list(self._databases.keys())

    def get_all_databases(self) -> Dict[str, DatabaseEntry]:
        """Get all registered databases."""
        return self._databases.copy()

    def get_all_schemas(self, db_id: str) -> List[str]:
        """Get all schemas for a database."""
        db = self.get_database(db_id)
        return db.schemas if db else []

    def validate_schema(self, db_id: str, schema_name: str) -> bool:
        """Check if schema is valid for the given database."""
        db = self.get_database(db_id)
        return schema_name in db.schemas if db else False

    def resolve_schema(self, db_id: str, schema_name: str) -> Optional[str]:
        """Resolve schema name: return as-is if valid, otherwise fallback to
        the first allowed schema for the database. Returns None if db not found."""
        db = self.get_database(db_id)
        if not db:
            return None
        if schema_name in db.schemas:
            return schema_name
        return db.schemas[0] if db.schemas else None

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get global setting value."""
        return self._settings.get(key, default)

    def get_default_batch_size(self) -> int:
        """Get default batch size for CSV export."""
        return self._settings.get('default_batch_size', 10000)

    def get_max_file_size_mb(self) -> int:
        """Get maximum file size in MB before splitting."""
        return self._settings.get('max_file_size_mb', 1024)

    def get_job_status_db_path(self) -> str:
        """Get path to job status SQLite database."""
        return self._settings.get('job_status_db_path', '/app/dbdata/job_status.db')

    @classmethod
    def reset_instance(cls):
        """Reset singleton instance (useful for testing)."""
        cls._instance = None
