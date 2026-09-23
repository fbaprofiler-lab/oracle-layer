"""
Oracle Layer — Calibrated Laya Client
Combines Laya System 1 decisions with OracleCalibrator for production-ready calibrated probabilities.
"""

import sys
sys.path.insert(0, '/home/openclaw/.openclaw/workspace/oracle-layer/src')

from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

from oracle.judgment.laya_client import LayaClient, LayaDecisionType, LayaInput, LayaOutput
from oracle.judgment.calibrator import OracleCalibrator, CalibrationFeatures


class CalibratedLayaClient:
    """
    Laya Client with OracleCalibrator integration.
    Produces production-ready calibrated probabilities from raw Laya outputs.
    """
    
    def __init__(
        self,
        calibrator_path: Optional[str] = None,
        laya_mode: str = "local",
        laya_remote_url: str = "http://localhost:8000",
        preload: bool = True,
        device: str = "cpu",
        api_key: Optional[str] = None,
    ):
        self.laya_client = LayaClient(
            mode=laya_mode,
            remote_url=laya_remote_url,
            preload=preload,
            device=device,
            api_key=api_key,
        )
        self.calibrator = None
        self.calibrator_path = calibrator_path
        
        if calibrator_path:
            self.load_calibrator(calibrator_path)
    
    def load_calibrator(self, path: str):
        """Load pre-trained OracleCalibrator."""
        self.calibrator = OracleCalibrator.load(path)
        self.calibrator_path = path
        print(f"Loaded calibrator: {self.calibrator.best_model_name} (Brier: {self.calibrator.training_metadata['best_brier']:.4f}, ECE: {self.calibrator.training_metadata['best_ece']:.4f})")
    
    def train_calibrator(self, evaluation_files: List[str]) -> Dict[str, Any]:
        """Train a new calibrator from evaluation data."""
        self.calibrator = OracleCalibrator()
        results = self.calibrator.train(evaluation_files)
        return results
    
    def save_calibrator(self, path: Optional[str] = None) -> str:
        """Save the current calibrator."""
        if not self.calibrator:
            raise RuntimeError("No calibrator trained or loaded")
        saved_path = self.calibrator.save(path)
        self.calibrator_path = saved_path
        return saved_path
    
    def _extract_calibration_features(self, laya_output: LayaOutput, input_data: LayaInput) -> CalibrationFeatures:
        """Extract features for calibrator from Laya output and input."""
        features = input_data.features
        context = input_data.context
        
        return CalibrationFeatures(
            jev_prob=laya_output.probability,
            category=features.get('category', 'unknown'),
            latest_market_price=features.get('current_price') or features.get('latest_market_price'),
            volume_24h=features.get('volume_24h'),
            smart_money_net_flow=features.get('smart_money_net_flow'),
            wallet_concentration=features.get('wallet_concentration'),
            momentum_signal=features.get('momentum_signal', 'neutral'),
            macro_wti=context.get('wti'),
            macro_gasoline_crack=context.get('gasoline_crack'),
            macro_diesel_crack=context.get('diesel_crack'),
            macro_gpr=context.get('gpr'),
            macro_dxy=context.get('dxy'),
            macro_fed_funds=context.get('fed_funds'),
            macro_breakeven_5y5y=context.get('breakeven_5y5y'),
            macro_cass_freight=context.get('cass_freight'),
        )
    
    async def judge_calibrated(self, input_data: LayaInput) -> LayaOutput:
        """Make a calibrated judgment: Laya -> OracleCalibrator."""
        
        # Get raw Laya prediction
        raw_output = await self.laya_client.judge(input_data)
        
        # Apply calibration if available
        if self.calibrator and self.calibrator.trained:
            cal_features = self._extract_calibration_features(raw_output, input_data)
            calibrated_prob = self.calibrator.predict(cal_features)
            
            # Update output with calibrated probability
            raw_output.probability = calibrated_prob
            raw_output.calibration_metadata["calibrated"] = True
            raw_output.calibration_metadata["calibrator_model"] = self.calibrator.best_model_name
            raw_output.calibration_metadata["raw_probability"] = raw_output.probability
            raw_output.reasoning = f"Laya {raw_output.routing_info.get('model', 'unknown')} -> Calibrated ({self.calibrator.best_model_name}): {calibrated_prob:.4f}"
        else:
            raw_output.calibration_metadata["calibrated"] = False
        
        return raw_output
    
    async def close(self):
        await self.laya_client.close()


async def judge_market_move_calibrated(
    market_id: str,
    features: Dict,
    context: Dict,
    calibrated_client: 'CalibratedLayaClient' = None,
    **client_kwargs
) -> LayaOutput:
    """Quick calibrated judgment for a market move prediction."""
    if calibrated_client is None:
        calibrated_client = CalibratedLayaClient(**client_kwargs)
    
    input_data = LayaInput(
        decision_type=LayaDecisionType.MARKET_MOVE,
        market_id=market_id,
        question="Will the YES probability increase in the next 24 hours?",
        features=features,
        context=context,
    )
    
    return await calibrated_client.judge_calibrated(input_data)
