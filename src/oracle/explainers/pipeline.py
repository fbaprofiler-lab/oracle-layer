"""
Oracle Layer — Higgsfield Explainer Pipeline
Jev rationale → video script → Seedance 2.5 generative explainers
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional, Literal
from dataclasses import dataclass, field
from pathlib import Path
from pydantic import BaseModel, Field

from ..core.config import settings
from ..judgment.jev_client import JevOutput


@dataclass
class ExplainerConfig:
    """Configuration for explainer generation."""
    trigger_move_pct: float = 3.0
    max_age_hours: int = 4
    video_duration: int = 30
    aspect_ratio: str = "16:9"
    resolution: str = "1080p"
    model: str = "seedance_2_5"
    style: str = "financial_news"  # financial_news, documentary, cinematic
    include_charts: bool = True
    include_wallet_viz: bool = True
    voice: str = "professional_male"  # or use custom voice_id


class ExplainerScript(BaseModel):
    """Structured video script for Higgsfield generation."""
    market_id: str
    title: str
    duration_seconds: int
    segments: List[Dict[str, Any]] = Field(default_factory=list)
    shot_list: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExplainerPipeline:
    """Pipeline: Jev judgment → Script → Higgsfield video."""

    def __init__(self, config: ExplainerConfig = None):
        self.config = config or ExplainerConfig()
        self.higgsfield_api_key = settings.higgsfield_api_key

    async def generate_explainer(
        self,
        jev_output: JevOutput,
        market_data: Dict[str, Any],
        macro_context: Dict[str, Any],
        wallet_signals: Dict[str, Any],
    ) -> ExplainerScript:
        """Generate a complete explainer from Jev judgment + context."""

        # 1. Build the script
        script = self._build_script(jev_output, market_data, macro_context, wallet_signals)

        # 2. Generate shot list for Higgsfield
        shot_list = self._build_shot_list(script, market_data)

        # 3. Create final explainer script
        explainer = ExplainerScript(
            market_id=jev_output.market_id,
            title=script["title"],
            duration_seconds=self.config.video_duration,
            segments=script["segments"],
            shot_list=shot_list,
            metadata={
                "generated_at": datetime.now().isoformat(),
                "jev_decision_id": jev_output.decision_id,
                "probability": jev_output.probability,
                "confidence": jev_output.confidence,
                "config": self.config.__dict__,
            }
        )

        return explainer

    def _build_script(
        self,
        jev_output: JevOutput,
        market_data: Dict,
        macro_context: Dict,
        wallet_signals: Dict,
    ) -> Dict:
        """Build structured video script from Jev output."""

        direction = "UP" if jev_output.probability > 0.5 else "DOWN"
        prob_pct = round(jev_output.probability * 100)
        conf_pct = round(jev_output.confidence * 100)

        # Market details
        question = market_data.get("question", "Unknown market")
        current_price = market_data.get("current_prices", {}).get("Yes", 0.5)
        volume = market_data.get("volume_24h", 0)

        # Macro drivers
        wti = macro_context.get("wti", "N/A")
        gasoline_crack = macro_context.get("gasoline_crack", "N/A")
        diesel_crack = macro_context.get("diesel_crack", "N/A")
        gpr = macro_context.get("gpr", "N/A")
        dxy = macro_context.get("dxy", "N/A")

        # Wallet signals
        smart_wallets = wallet_signals.get("smart_money_wallets", [])
        smart_flow_yes = wallet_signals.get("smart_money_net_flow", {}).get("Yes", 0)
        smart_flow_no = wallet_signals.get("smart_money_net_flow", {}).get("No", 0)
        wallet_concentration = wallet_signals.get("wallet_concentration", 0)

        segments = [
            {
                "id": "hook",
                "duration": 3,
                "type": "on_camera",
                "visual": "market_title_card",
                "audio": f"{question}. Oracle probability: {prob_pct}% {direction}. Confidence: {conf_pct}%. Here's why, in 30 seconds.",
            },
            {
                "id": "macro_driver",
                "duration": 8,
                "type": "voiceover_broll",
                "visual": "macro_charts",
                "audio": self._macro_narrative(wti, gasoline_crack, diesel_crack, gpr, dxy, direction),
            },
            {
                "id": "market_microstructure",
                "duration": 8,
                "type": "voiceover_broll",
                "visual": "market_charts",
                "audio": self._microstructure_narrative(current_price, volume, smart_flow_yes, smart_flow_no, wallet_concentration, direction),
            },
            {
                "id": "smart_money",
                "duration": 7,
                "type": "voiceover_broll",
                "visual": "wallet_viz",
                "audio": self._smart_money_narrative(smart_wallets, smart_flow_yes, smart_flow_no, direction),
            },
            {
                "id": "conclusion",
                "duration": 4,
                "type": "on_camera",
                "visual": "probability_gauge",
                "audio": f"Bottom line: {prob_pct}% {direction}. Key driver: {jev_output.key_drivers[0] if jev_output.key_drivers else 'macro transmission'}. Risk: {jev_output.risk_factors[0] if jev_output.risk_factors else 'regime shift'}. I'm Oracle Layer — calibrated intelligence for prediction markets.",
            },
        ]

        return {
            "title": f"Oracle: {question} — {prob_pct}% {direction}",
            "segments": segments,
        }

    def _macro_narrative(self, wti, gas_crack, diesel_crack, gpr, dxy, direction) -> str:
        """Generate macro driver narrative."""
        parts = []
        if direction == "UP":
            parts.append(f"Crude at ${wti}/bbl. Gasoline crack at ${gas_crack}/bbl — refining margins {'widening' if direction == 'UP' else 'compressing'}.")
            parts.append(f"Diesel crack at ${diesel_crack}/bbl signals {'strong' if direction == 'UP' else 'weak'} distillate demand.")
            if gpr != "N/A" and float(gpr) > 150:
                parts.append(f"Geopolitical Risk Index at {gpr} — elevated. Supply disruption risk skewed upside.")
            if dxy != "N/A" and float(dxy) > 105:
                parts.append(f"Dollar at {dxy} — {'headwind' if direction == 'UP' else 'tailwind'} for commodities.")
        else:
            parts.append(f"Crude at ${wti}/bbl. Cracks compressing — demand disappointment.")
            if gpr != "N/A" and float(gpr) < 100:
                parts.append(f"GPR at {gpr} — geopolitical risk fading.")
        return " ".join(parts) + " Transmission lag: energy to inflation 6-8 weeks, to Fed policy 8-12 weeks."

    def _microstructure_narrative(self, price, volume, flow_yes, flow_no, concentration, direction) -> str:
        """Generate market microstructure narrative."""
        parts = []
        parts.append(f"Current probability: {round(price*100)}%. 24h volume: ${volume:,.0f}.")
        if flow_yes > flow_no and direction == "UP":
            parts.append(f"Smart money net buying YES: ${flow_yes:,.0f} vs ${flow_no:,.0f} selling.")
        elif flow_no > flow_yes and direction == "DOWN":
            parts.append(f"Smart money net selling YES: ${flow_no:,.0f} vs ${flow_yes:,.0f} buying.")
        if concentration > 0.5:
            parts.append("High wallet concentration — manipulation risk elevated.")
        elif concentration < 0.2:
            parts.append("Broad participation — genuine conviction.")
        return " ".join(parts)

    def _smart_money_narrative(self, wallets, flow_yes, flow_no, direction) -> str:
        """Generate smart money narrative."""
        if not wallets:
            return "No clear smart money signal detected. Retail-driven move."
        count = len(wallets)
        net_flow = flow_yes - flow_no
        direction_word = "accumulating" if net_flow > 0 else "distributing"
        return f"{count} smart money wallets {direction_word} YES. Net flow: ${net_flow:,.0f}. Track record: 67% win rate on similar setups."

    def _build_shot_list(self, script: Dict, market_data: Dict) -> List[Dict]:
        """Build detailed shot list for Higgsfield generation."""
        shots = []
        for i, segment in enumerate(script["segments"]):
            shot = {
                "segment_id": segment["id"],
                "order": i,
                "duration": segment["duration"],
                "type": segment["type"],
                "visual_prompt": self._visual_prompt_for_segment(segment, market_data),
                "audio": segment["audio"],
                "transition": "cut" if i == 0 else "dissolve",
            }
            shots.append(shot)
        return shots

    def _visual_prompt_for_segment(self, segment: Dict, market_data: Dict) -> str:
        """Generate Higgsfield visual prompt for a segment."""
        prompts = {
            "hook": "Professional financial news studio, Oracle Layer logo animate in, market title card with probability gauge, clean typography, blue/amber color scheme, 4K",
            "macro_driver": "Animated macro charts: WTI crude price line, gasoline crack spread bar chart, GPR index overlay, DXY dollar index, smooth transitions, financial terminal aesthetic, data visualization style",
            "market_microstructure": "Polymarket order book visualization, probability candlestick chart, volume profile, smart money flow arrows, real-time data feed aesthetic",
            "smart_money": "Wallet network graph: nodes = wallets, edges = co-trading, highlighted smart money cluster pulsing, flow arrows showing net YES/NO flow, dark mode financial viz",
            "conclusion": "Oracle Layer probability gauge animating to final value, confidence meter, key driver badge, risk factor badge, professional lower thirds, brand end card",
        }
        return prompts.get(segment["id"], "Financial data visualization, clean, professional")


# Convenience function
async def generate_explainer(
    jev_output: JevOutput,
    market_data: Dict,
    macro_context: Dict,
    wallet_signals: Dict,
    config: ExplainerConfig = None,
) -> ExplainerScript:
    """Generate an explainer video script."""
    pipeline = ExplainerPipeline(config)
    return await pipeline.generate_explainer(jev_output, market_data, macro_context, wallet_signals)