from typing import Dict, Type
from core.base_database import BaseDatabaseAdapter
from core.database_registry import DatabaseEntry

from .cdm_adapter import CDMAdapter
from .kmimic_adapter import KMIMICAdapter
from .mimiciv_adapter import MIMICIVAdapter
from .inspire_adapter import INSPIREAdapter
from .synthea_adapter import SyntheaAdapter

# Registry of adapter classes by database ID
ADAPTER_REGISTRY: Dict[str, Type[BaseDatabaseAdapter]] = {
    'cdm': CDMAdapter,
    'kmimic': KMIMICAdapter,
    'mimiciv': MIMICIVAdapter,
    'inspire': INSPIREAdapter,
    'synthea': SyntheaAdapter,
}


def get_adapter(config: DatabaseEntry) -> BaseDatabaseAdapter:
    """
    Get the appropriate adapter for a database configuration.

    Args:
        config: Database configuration entry

    Returns:
        Instantiated adapter

    Raises:
        ValueError: If no adapter found for database
    """
    adapter_class = ADAPTER_REGISTRY.get(config.db_id)
    if adapter_class is None:
        raise ValueError(f"No adapter found for database: {config.db_id}")
    return adapter_class(config)


__all__ = [
    'BaseDatabaseAdapter',
    'CDMAdapter',
    'KMIMICAdapter',
    'MIMICIVAdapter',
    'INSPIREAdapter',
    'SyntheaAdapter',
    'get_adapter',
    'ADAPTER_REGISTRY'
]
