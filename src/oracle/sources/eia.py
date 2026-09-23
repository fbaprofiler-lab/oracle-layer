"""
Oracle Layer — EIA (U.S. Energy Information Administration) Data Source
Fixed for EIA v2 API (facet-based queries)
"""

import os
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
import httpx
import pandas as pd

from .base import DataSource, DataPoint, registry
from ..core.config import settings


class EIASource(DataSource):
    """EIA Open Data API v2 connector."""

    BASE_URL = "https://api.eia.gov/v2/"

    # Key series for Oracle Layer - mapped to v2 API facets (verified working)
    # Format: {series_id: {endpoint, facets, frequency, unit}}
    SERIES = {
        # Weekly retail prices (Dollars per Gallon)
        "gasoline_us": {
            "endpoint": "petroleum/pri/gnd/data/",
            "facets": {"product": ["EPM0"], "duoarea": ["NUS"], "process": ["PTE"]},
            "frequency": "weekly",
            "unit": "usd/gallon",
            "value_field": "value",
        },
        "diesel_us": {
            "endpoint": "petroleum/pri/gnd/data/",
            "facets": {"product": ["EPD2D"], "duoarea": ["NUS"], "process": ["PTE"]},
            "frequency": "weekly",
            "unit": "usd/gallon",
            "value_field": "value",
        },
        # By PADD (1-5)
        "gasoline_padd1": {
            "endpoint": "petroleum/pri/gnd/data/",
            "facets": {"product": ["EPM0"], "duoarea": ["R1X"], "process": ["PTE"]},
            "frequency": "weekly",
            "unit": "usd/gallon",
            "value_field": "value",
        },
        "gasoline_padd2": {
            "endpoint": "petroleum/pri/gnd/data/",
            "facets": {"product": ["EPM0"], "duoarea": ["R2X"], "process": ["PTE"]},
            "frequency": "weekly",
            "unit": "usd/gallon",
            "value_field": "value",
        },
        "gasoline_padd3": {
            "endpoint": "petroleum/pri/gnd/data/",
            "facets": {"product": ["EPM0"], "duoarea": ["R3X"], "process": ["PTE"]},
            "frequency": "weekly",
            "unit": "usd/gallon",
            "value_field": "value",
        },
        "gasoline_padd4": {
            "endpoint": "petroleum/pri/gnd/data/",
            "facets": {"product": ["EPM0"], "duoarea": ["R4X"], "process": ["PTE"]},
            "frequency": "weekly",
            "unit": "usd/gallon",
            "value_field": "value",
        },
        "gasoline_padd5": {
            "endpoint": "petroleum/pri/gnd/data/",
            "facets": {"product": ["EPM0"], "duoarea": ["R5X"], "process": ["PTE"]},
            "frequency": "weekly",
            "unit": "usd/gallon",
            "value_field": "value",
        },
        # Weekly Petroleum Status Report (stocks) - Ending Stocks (MBBL)
        "crude_stocks": {
            "endpoint": "petroleum/stoc/wstk/data/",
            "facets": {"product": ["EPC0"], "duoarea": ["NUS"], "process": ["SAE"]},
            "frequency": "weekly",
            "unit": "million_barrels",
            "value_field": "value",
        },
        "gasoline_stocks": {
            "endpoint": "petroleum/stoc/wstk/data/",
            "facets": {"product": ["EPM0"], "duoarea": ["NUS"], "process": ["SAE"]},
            "frequency": "weekly",
            "unit": "million_barrels",
            "value_field": "value",
        },
        "distillate_stocks": {
            "endpoint": "petroleum/stoc/wstk/data/",
            "facets": {"product": ["EPD0"], "duoarea": ["NUS"], "process": ["SAE"]},
            "frequency": "weekly",
            "unit": "million_barrels",
            "value_field": "value",
        },
        # Monthly production (no weekly production endpoint available)
        "crude_production": {
            "endpoint": "petroleum/crd/crpdn/data/",
            "facets": {"duoarea": ["NUS"]},
            "frequency": "monthly",
            "unit": "thousand_barrels_daily",
            "value_field": "value",
        },
        # Note: Weekly refinery runs / production endpoints (pnp/wref) don't exist in v2 API
        # Use monthly refinery runs instead
        "refinery_runs_monthly": {
            "endpoint": "petroleum/pnp/mref/data/",
            "facets": {"duoarea": ["NUS"]},
            "frequency": "monthly",
            "unit": "thousand_barrels_daily",
            "value_field": "value",
        },
    }

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("eia", config)
        self.api_key = config.get("api_key") or settings.eia_api_key or os.getenv("EIA_API_KEY")
        if not self.api_key:
            raise ValueError("EIA_API_KEY required for EIASource")
        self.client = httpx.AsyncClient(timeout=30.0)

    @property
    def available_series(self) -> List[str]:
        return list(self.SERIES.keys())

    async def health_check(self) -> bool:
        try:
            await self.fetch_series("gasoline_us", limit=1)
            return True
        except Exception:
            return False

    async def fetch_series(self, series_id: str, **kwargs) -> List[DataPoint]:
        """Fetch a single EIA series using v2 facet-based API."""
        series_config = self.SERIES.get(series_id)
        if not series_config:
            # Fallback: try as direct series ID
            return await self._fetch_raw_series(series_id, **kwargs)

        limit = kwargs.get("limit", 5000)

        # Build v2 API query parameters
        params = {
            "api_key": self.api_key,
            "frequency": series_config["frequency"],
            "data[0]": series_config["value_field"],
            "length": limit,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
        }

        # Add facets
        for facet_name, facet_values in series_config.get("facets", {}).items():
            for i, val in enumerate(facet_values):
                params[f"facets[{facet_name}][{i}]"] = val

        url = f"{self.BASE_URL}{series_config['endpoint']}"
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        records = data.get("response", {}).get("data", [])
        points = []

        for record in records:
            try:
                timestamp = pd.to_datetime(record["period"])
                value = float(record["value"]) if record["value"] not in (None, ".") else None
                if value is not None:
                    points.append(DataPoint(
                        source="eia",
                        series_id=series_id,
                        timestamp=timestamp.to_pydatetime(),
                        value=value,
                        unit=series_config.get("unit", ""),
                        metadata={
                            "eia_endpoint": series_config["endpoint"],
                            "eia_facets": series_config["facets"],
                            "raw_period": record["period"]
                        }
                    ))
            except (KeyError, ValueError, TypeError):
                continue

        return points

    async def _fetch_raw_series(self, series_id: str, **kwargs) -> List[DataPoint]:
        """Fallback for raw series IDs (legacy compatibility)."""
        limit = kwargs.get("limit", 5000)
        params = {"api_key": self.api_key, "length": limit}
        url = f"{self.BASE_URL}seriesid/{series_id}"
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        records = data.get("response", {}).get("data", [])
        points = []
        for record in records:
            try:
                timestamp = pd.to_datetime(record["period"])
                value = float(record["value"]) if record["value"] not in (None, ".") else None
                if value is not None:
                    points.append(DataPoint(
                        source="eia",
                        series_id=series_id,
                        timestamp=timestamp.to_pydatetime(),
                        value=value,
                        unit="",
                        metadata={"eia_series_id": series_id, "raw_period": record["period"]}
                    ))
            except (KeyError, ValueError, TypeError):
                continue
        return points

    async def fetch_multiple(self, series_ids: List[str], **kwargs) -> Dict[str, List[DataPoint]]:
        """Fetch multiple series with rate limiting."""
        results = {}
        semaphore = asyncio.Semaphore(3)  # Max 3 concurrent requests

        async def fetch_one(sid: str):
            async with semaphore:
                try:
                    points = await self.fetch_series(sid, **kwargs)
                    results[sid] = points
                    await asyncio.sleep(0.1)  # Rate limit
                except Exception as e:
                    results[sid] = []
                    print(f"EIA fetch failed for {sid}: {e}")

        await asyncio.gather(*[fetch_one(sid) for sid in series_ids])
        return results

    async def close(self):
        await self.client.aclose()


# Register the source
eia_source = EIASource({"api_key": settings.eia_api_key})
registry.register(eia_source)