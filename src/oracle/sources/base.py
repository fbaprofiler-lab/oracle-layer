"""
Oracle Layer — Base Data Source Classes
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import asyncio


@dataclass
class DataPoint:
    """A single data point from a source."""
    source: str
    series_id: str
    timestamp: datetime
    value: float
    unit: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "series_id": self.series_id,
            "timestamp": self.timestamp.isoformat(),
            "value": self.value,
            "unit": self.unit,
            "metadata": self.metadata,
        }


class DataSource(ABC):
    """Abstract base class for all data sources."""

    def __init__(self, name: str, config: Dict[str, Any] = None):
        self.name = name
        self.config = config or {}
        self._session = None

    @abstractmethod
    async def fetch_series(self, series_id: str, **kwargs) -> List[DataPoint]:
        """Fetch a single series from the source."""
        pass

    @abstractmethod
    async def fetch_multiple(self, series_ids: List[str], **kwargs) -> Dict[str, List[DataPoint]]:
        """Fetch multiple series efficiently."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the source is available."""
        pass

    @property
    @abstractmethod
    def available_series(self) -> List[str]:
        """Return list of available series IDs."""
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """Clean up resources."""
        pass


class SourceRegistry:
    """Registry for managing data sources."""

    def __init__(self):
        self._sources: Dict[str, DataSource] = {}

    def register(self, source: DataSource):
        """Register a data source."""
        self._sources[source.name] = source

    def get(self, name: str) -> Optional[DataSource]:
        """Get a source by name."""
        return self._sources.get(name)

    def list_sources(self) -> List[str]:
        """List all registered source names."""
        return list(self._sources.keys())

    async def fetch_all_series(self, series_map: Dict[str, List[str]]) -> Dict[str, List[DataPoint]]:
        """Fetch series from multiple sources in parallel."""
        tasks = []
        for source_name, series_ids in series_map.items():
            source = self.get(source_name)
            if source:
                tasks.append(source.fetch_multiple(series_ids))
            else:
                raise ValueError(f"Source not registered: {source_name}")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        combined = {}
        for source_name, result in zip(series_map.keys(), results):
            if isinstance(result, Exception):
                raise result
            combined.update(result)

        return combined


# Global registry instance
registry = SourceRegistry()