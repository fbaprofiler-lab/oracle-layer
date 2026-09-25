"""
Oracle Layer — Calibration Monitoring API
REST endpoints for calibration dashboard and regression alerts.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import json

from ..calibration.monitor import CalibrationMonitor, run_calibration_monitor
from ..calibration.leakage_scanner import run_leakage_scan

router = APIRouter(prefix="/api/v1/calibration", tags=["calibration"])

_monitor = CalibrationMonitor()


class CalibrationStatusResponse(BaseModel):
    status: str
    date: str
    snapshot: Optional[Dict[str, Any]] = None
    new_alerts: int = 0
    alerts: List[Dict[str, Any]] = []


class DashboardResponse(BaseModel):
    snapshots: List[Dict[str, Any]]
    active_alerts: List[Dict[str, Any]]
    summary: Dict[str, Any]


class LeakageScanRequest(BaseModel):
    pre_reg_file: str
    raw_data_file: Optional[str] = None
    eval_report_file: Optional[str] = None


class LeakageScanResponse(BaseModel):
    total_findings: int
    by_severity: Dict[str, int]
    by_type: Dict[str, int]
    critical_count: int
    passed: bool
    findings: List[Dict[str, Any]]


@router.get("/status", response_model=CalibrationStatusResponse)
async def get_calibration_status():
    """Get current calibration status (runs daily check if not run today)."""
    result = await _monitor.run_daily_check()
    return CalibrationStatusResponse(**result)


@router.get("/dashboard", response_model=DashboardResponse)
async def get_calibration_dashboard():
    """Get full calibration dashboard data."""
    data = _monitor.get_dashboard_data()
    return DashboardResponse(**data)


@router.post("/scan", response_model=CalibrationStatusResponse)
async def trigger_calibration_scan():
    """Manually trigger calibration check."""
    result = await run_calibration_monitor()
    return CalibrationStatusResponse(**result)


@router.post("/leakage", response_model=LeakageScanResponse)
async def run_leakage_scan_endpoint(request: LeakageScanRequest):
    """Run leakage detection scan on evaluation files."""
    result = run_leakage_scan(
        request.pre_reg_file,
        request.raw_data_file,
        request.eval_report_file
    )
    response = dict(result)
    response["passed"] = response.pop("pass")
    return LeakageScanResponse(**response)


@router.get("/history")
async def get_calibration_history(days: int = Query(30, ge=1, le=90)):
    """Get calibration history for specified days."""
    data = _monitor.get_dashboard_data()
    # Filter to requested days
    cutoff = datetime.now()
    filtered_snapshots = [
        s for s in data["snapshots"]
        if datetime.strptime(s["date"], "%Y-%m-%d") >= cutoff.replace(day=cutoff.day - days)
    ]
    return {
        "snapshots": filtered_snapshots,
        "active_alerts": data["active_alerts"],
        "summary": data["summary"],
    }
