"""
Oracle Layer — Database Models (SQLAlchemy + TimescaleDB)
Persistent storage for signals, calibration history, and macro data.
"""

import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime, Text,
    Boolean, JSON, Index, ForeignKey, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
import uuid

from .config import settings

Base = declarative_base()


class OracleSignal(Base):
    """Fused Oracle signal with all component data."""
    __tablename__ = "oracle_signals"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id = Column(String(100), unique=True, nullable=False, index=True)
    market_id = Column(String(66), nullable=False, index=True)
    question = Column(Text, nullable=False)
    category = Column(String(100), nullable=False, index=True)
    
    # Macro component
    macro_drivers = Column(JSON, default={})
    macro_signal_strength = Column(String(20), nullable=False)
    transmission_lag_weeks = Column(JSON, default={})
    
    # Market component
    market_metrics = Column(JSON, default={})
    market_signal_strength = Column(String(20), nullable=False)
    
    # Jev judgment
    jev_probability = Column(Float, nullable=False)
    jev_confidence = Column(Float, nullable=False)
    jev_reasoning = Column(Text)
    jev_key_drivers = Column(JSON, default=[])
    jev_risk_factors = Column(JSON, default=[])
    
    # Fused output
    fused_probability_up = Column(Float, nullable=False)
    fused_confidence = Column(Float, nullable=False)
    key_drivers = Column(JSON, default=[])
    risk_factors = Column(JSON, default=[])
    
    # Explainer
    explainer_script = Column(JSON, nullable=True)
    explainer_video_url = Column(String(500), nullable=True)
    
    # Metadata
    metadata_json = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    resolved_at = Column(DateTime, nullable=True)
    actual_outcome = Column(Boolean, nullable=True)  # For calibration
    
    __table_args__ = (
        Index('ix_signals_category_created', 'category', 'created_at'),
        Index('ix_signals_market_resolved', 'market_id', 'resolved_at'),
    )


class CalibrationRecord(Base):
    """Historical calibration metrics for tracking model performance."""
    __tablename__ = "calibration_records"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id = Column(String(100), unique=True, nullable=False, index=True)
    model_name = Column(String(50), nullable=False)  # 'isotonic', 'temperature', 'logistic'
    
    # Metrics
    n_samples = Column(Integer, nullable=False)
    accuracy = Column(Float, nullable=False)
    brier_score = Column(Float, nullable=False)
    ece = Column(Float, nullable=False)
    reliability = Column(String(20), nullable=False)
    
    # Calibration curve
    calibration_curve = Column(JSON, default=[])
    by_category = Column(JSON, default={})
    
    # Gates
    gate_ece_passed = Column(Boolean, nullable=False)
    gate_brier_passed = Column(Boolean, nullable=False)
    gate_hitrate_passed = Column(Boolean, nullable=False)
    gate_n_passed = Column(Boolean, nullable=False)
    verdict = Column(String(20), nullable=False)
    
    # Metadata
    training_data_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class MacroSnapshot(Base):
    """Time-series macro data snapshots."""
    __tablename__ = "macro_snapshots"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    # EIA
    gasoline_us = Column(Float, nullable=True)
    diesel_us = Column(Float, nullable=True)
    gasoline_stocks = Column(Float, nullable=True)
    distillate_stocks = Column(Float, nullable=True)
    crude_stocks = Column(Float, nullable=True)
    crude_production = Column(Float, nullable=True)
    gasoline_production = Column(Float, nullable=True)
    distillate_production = Column(Float, nullable=True)
    crude_runs = Column(Float, nullable=True)
    
    # FRED
    wti = Column(Float, nullable=True)
    brent = Column(Float, nullable=True)
    rbo_b = Column(Float, nullable=True)
    ho = Column(Float, nullable=True)
    dxy = Column(Float, nullable=True)
    gpr = Column(Float, nullable=True)
    fed_funds = Column(Float, nullable=True)
    breakeven_5y5y = Column(Float, nullable=True)
    cass_freight = Column(Float, nullable=True)
    
    # Derived
    gasoline_crack = Column(Float, nullable=True)
    diesel_crack = Column(Float, nullable=True)
    wti_brent_spread = Column(Float, nullable=True)
    
    __table_args__ = (
        Index('ix_macro_timestamp', 'timestamp'),
    )


class WalletSignal(Base):
    """Smart money wallet tracking."""
    __tablename__ = "wallet_signals"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_address = Column(String(66), nullable=False, index=True)
    market_id = Column(String(66), nullable=False, index=True)
    
    # Analysis
    is_smart_money = Column(Boolean, default=False)
    trades_count = Column(Integer, default=0)
    volume_24h = Column(Float, default=0)
    net_flow = Column(Float, default=0)
    two_sided_share = Column(Float, default=0)
    median_dwell_seconds = Column(Integer, default=0)
    mm_flags = Column(JSON, default=[])
    clusters = Column(Integer, default=0)
    
    # Metadata
    last_active = Column(DateTime, nullable=True)
    analyzed_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        UniqueConstraint('wallet_address', 'market_id', name='uq_wallet_market'),
        Index('ix_wallet_smart_analyzed', 'is_smart_money', 'analyzed_at'),
    )


# Database engine and session factory
engine = None
SessionLocal = None


def get_engine():
    """Get or create database engine."""
    global engine
    if engine is None:
        engine = create_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=settings.environment == "development",
        )
    return engine


def get_session() -> Session:
    """Get a new database session."""
    global SessionLocal
    if SessionLocal is None:
        SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return SessionLocal()


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=get_engine())
    print("Database tables created")


def drop_db():
    """Drop all tables (use with caution)."""
    Base.metadata.drop_all(bind=get_engine())
    print("Database tables dropped")


# Repository functions
class SignalRepository:
    """Repository for OracleSignal operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def save(self, signal: OracleSignal) -> OracleSignal:
        self.session.merge(signal)
        self.session.commit()
        return signal
    
    def get_by_id(self, signal_id: str) -> Optional[OracleSignal]:
        return self.session.query(OracleSignal).filter(
            OracleSignal.signal_id == signal_id
        ).first()
    
    def get_by_market(self, market_id: str) -> List[OracleSignal]:
        return self.session.query(OracleSignal).filter(
            OracleSignal.market_id == market_id
        ).order_by(OracleSignal.created_at.desc()).all()
    
    def get_unresolved(self, hours: int = 24) -> List[OracleSignal]:
        """Get signals that need resolution."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return self.session.query(OracleSignal).filter(
            OracleSignal.resolved_at.is_(None),
            OracleSignal.created_at > cutoff
        ).all()
    
    def get_for_calibration(self, limit: int = 1000) -> List[OracleSignal]:
        """Get resolved signals for calibration training."""
        return self.session.query(OracleSignal).filter(
            OracleSignal.actual_outcome.isnot(None)
        ).order_by(OracleSignal.resolved_at.desc()).limit(limit).all()
    
    def record_outcome(self, signal_id: str, outcome: bool):
        """Record actual outcome for calibration."""
        signal = self.get_by_id(signal_id)
        if signal:
            signal.actual_outcome = outcome
            signal.resolved_at = datetime.utcnow()
            self.session.commit()


class CalibrationRepository:
    """Repository for CalibrationRecord operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def save(self, record: CalibrationRecord) -> CalibrationRecord:
        self.session.merge(record)
        self.session.commit()
        return record
    
    def get_latest(self) -> Optional[CalibrationRecord]:
        return self.session.query(CalibrationRecord).order_by(
            CalibrationRecord.created_at.desc()
        ).first()
    
    def get_history(self, limit: int = 20) -> List[CalibrationRecord]:
        return self.session.query(CalibrationRecord).order_by(
            CalibrationRecord.created_at.desc()
        ).limit(limit).all()


class MacroRepository:
    """Repository for MacroSnapshot operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def save(self, snapshot: MacroSnapshot) -> MacroSnapshot:
        self.session.merge(snapshot)
        self.session.commit()
        return snapshot
    
    def get_latest(self) -> Optional[MacroSnapshot]:
        return self.session.query(MacroSnapshot).order_by(
            MacroSnapshot.timestamp.desc()
        ).first()
    
    def get_range(self, start: datetime, end: datetime) -> List[MacroSnapshot]:
        return self.session.query(MacroSnapshot).filter(
            MacroSnapshot.timestamp >= start,
            MacroSnapshot.timestamp <= end
        ).order_by(MacroSnapshot.timestamp).all()


class WalletRepository:
    """Repository for WalletSignal operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def save(self, signal: WalletSignal) -> WalletSignal:
        self.session.merge(signal)
        self.session.commit()
        return signal
    
    def get_smart_money(self, market_id: str) -> List[WalletSignal]:
        return self.session.query(WalletSignal).filter(
            WalletSignal.market_id == market_id,
            WalletSignal.is_smart_money == True
        ).all()
    
    def get_by_wallet(self, wallet_address: str) -> List[WalletSignal]:
        return self.session.query(WalletSignal).filter(
            WalletSignal.wallet_address == wallet_address
        ).order_by(WalletSignal.analyzed_at.desc()).all()


# Convenience function to get repositories
def get_repositories() -> Dict[str, Any]:
    """Get all repositories with a new session."""
    session = get_session()
    return {
        "session": session,
        "signals": SignalRepository(session),
        "calibration": CalibrationRepository(session),
        "macro": MacroRepository(session),
        "wallets": WalletRepository(session),
    }
