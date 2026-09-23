"""
Oracle Layer — FRED (St. Louis Fed) Data Source
Fixed with verified working series IDs
"""

import os
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
import httpx
import pandas as pd

from .base import DataSource, DataPoint, registry
from ..core.config import settings


class FREDSource(DataSource):
    """FRED (Federal Reserve Economic Data) API connector."""

    BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

    # Key series for Oracle Layer - verified working series IDs
    SERIES = {
        # Crude & products
        "wti": "DCOILWTICO",          # WTI Crude Oil (daily)
        "brent": "DCOILBRENTEU",      # Brent Crude Oil (daily)
        "ho": "DHOILNYH",             # Heating Oil / ULSD (daily, $/gal)
        # RBOB gasoline futures: DRBOBNYH doesn't exist, use DHOILNYH for heating oil proxy
        # Crack spreads (computed from above)
        # Macro
        "dxy": "DTWEXBGS",            # Trade-weighted dollar index (broad, monthly)
        # GPRC (Geopolitical Risk) doesn't exist in public FRED - skip
        "cpi_all": "CPIAUCSL",        # CPI all items (monthly)
        "cpi_energy": "CPIENGSL",     # CPI energy (monthly)
        "cpi_gasoline": "CUSR0000SETB01",  # CPI gasoline (monthly)
        # Cass Freight Index: CASSFRTINDX doesn't exist in public FRED - skip
        # Inflation expectations
        "breakeven_5y5y": "T5YIE",    # 5y5y breakeven inflation (daily)
        "breakeven_10y": "T10YIE",    # 10y breakeven inflation (daily)
        "michigan_inflation": "MICH", # Michigan inflation expectations (monthly)
        # Rates
        "fed_funds": "FEDFUNDS",      # Effective federal funds rate (monthly)
        "sofr": "SOFR",               # Secured Overnight Financing Rate (daily)
        "t10y2y": "T10Y2Y",           # 10y-2y Treasury spread (daily)
        # Employment
        "unrate": "UNRATE",           # Unemployment rate (monthly)
        "payrolls": "PAYEMS",         # Total nonfarm payrolls (monthly, thousands)
        # Industrial
        "ip_total": "INDPRO",         # Industrial production index (monthly)
        "ip_manufacturing": "IPMAN",  # Manufacturing production index (monthly)
        # Consumer
        "retail_sales": "RSAFS",      # Retail sales (monthly, millions USD)
        "consumer_sentiment": "UMCSENT", # Michigan consumer sentiment (monthly)
    }

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("fred", config)
        self.api_key = config.get("api_key") or settings.fred_api_key or os.getenv("FRED_API_KEY")
        if not self.api_key:
            raise ValueError("FRED_API_KEY required for FREDSource")
        self.client = httpx.AsyncClient(timeout=30.0)

    @property
    def available_series(self) -> List[str]:
        return list(self.SERIES.keys())

    async def health_check(self) -> bool:
        try:
            await self.fetch_series("wti", limit=1)
            return True
        except Exception:
            return False

    async def fetch_series(self, series_id: str, **kwargs) -> List[DataPoint]:
        """Fetch a single FRED series."""
        fred_series_id = self.SERIES.get(series_id, series_id)
        limit = kwargs.get("limit", 5000)
        observation_start = kwargs.get("observation_start", "2020-01-01")

        params = {
            "series_id": fred_series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": observation_start,
            "limit": limit,
            "sort_order": "desc",
        }

        response = await self.client.get(self.BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()

        obs = data.get("observations", [])
        points = []

        for ob in obs:
            try:
                if ob["value"] in (".", None, ""):
                    continue
                timestamp = pd.to_datetime(ob["date"])
                value = float(ob["value"])
                points.append(DataPoint(
                    source="fred",
                    series_id=series_id,
                    timestamp=timestamp.to_pydatetime(),
                    value=value,
                    unit=self._get_unit(fred_series_id),
                    metadata={"fred_series_id": fred_series_id}
                ))
            except (KeyError, ValueError, TypeError):
                continue

        return points

    def _get_unit(self, fred_series_id: str) -> str:
        """Infer unit from FRED series ID."""
        units_map = {
            "DCOILWTICO": "usd/barrel",
            "DCOILBRENTEU": "usd/barrel",
            "DHOILNYH": "usd/gallon",
            "DTWEXBGS": "index",
            "CPIAUCSL": "index",
            "CPIENGSL": "index",
            "CUSR0000SETB01": "index",
            "T5YIE": "percent",
            "T10YIE": "percent",
            "MICH": "percent",
            "FEDFUNDS": "percent",
            "SOFR": "percent",
            "T10Y2Y": "percent",
            "UNRATE": "percent",
            "PAYEMS": "thousands",
            "INDPRO": "index",
            "IPMAN": "index",
            "RSAFS": "millions_usd",
            "UMCSENT": "index",
        }
        return units_map.get(fred_series_id, "")

    async def fetch_multiple(self, series_ids: List[str], **kwargs) -> Dict[str, List[DataPoint]]:
        """Fetch multiple series with rate limiting."""
        results = {}
        semaphore = asyncio.Semaphore(5)  # FRED allows more concurrent

        async def fetch_one(sid: str):
            async with semaphore:
                try:
                    points = await self.fetch_series(sid, **kwargs)
                    results[sid] = points
                    await asyncio.sleep(0.05)  # Rate limit
                except Exception as e:
                    results[sid] = []
                    print(f"FRED fetch failed for {sid}: {e}")

        await asyncio.gather(*[fetch_one(sid) for sid in series_ids])
        return results

    async def close(self):
        await self.client.aclose()


# Register the source
fred_source = FREDSource({"api_key": settings.fred_api_key})
registry.register(fred_source)