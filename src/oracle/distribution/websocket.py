"""
Oracle Layer — WebSocket Server
Real-time signal streaming for pro/trader clients
"""

import asyncio
import json
import logging
from typing import Dict, Set, Optional, Any
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..core.config import settings
from ..fusion.engine import FusionEngine, run_fusion_scan

logger = logging.getLogger(__name__)


class WebSocketServer:
    """WebSocket server for real-time Oracle signal streaming."""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.fusion_engine = FusionEngine()
        self._scan_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        if client_id not in self.active_connections:
            self.active_connections[client_id] = set()
        self.active_connections[client_id].add(websocket)
        logger.info(f"Client {client_id} connected. Active connections: {len(self.active_connections[client_id])}")

    def disconnect(self, websocket: WebSocket, client_id: str):
        """Remove a WebSocket connection."""
        if client_id in self.active_connections:
            self.active_connections[client_id].discard(websocket)
            if not self.active_connections[client_id]:
                del self.active_connections[client_id]
        logger.info(f"Client {client_id} disconnected")

    async def send_personal_message(self, message: dict, client_id: str):
        """Send a message to a specific client."""
        if client_id in self.active_connections:
            disconnected = set()
            for ws in self.active_connections[client_id]:
                if ws.client_state == WebSocketState.CONNECTED:
                    try:
                        await ws.send_json(message)
                    except Exception:
                        disconnected.add(ws)
            for ws in disconnected:
                self.active_connections[client_id].discard(ws)

    async def broadcast(self, message: dict, category: Optional[str] = None):
        """Broadcast a message to all connected clients, optionally filtered by category."""
        for client_id, connections in self.active_connections.items():
            # Filter by category if specified
            if category and client_id != category and client_id != "all":
                continue
            disconnected = set()
            for ws in connections:
                if ws.client_state == WebSocketState.CONNECTED:
                    try:
                        await ws.send_json(message)
                    except Exception:
                        disconnected.add(ws)
            for ws in disconnected:
                connections.discard(ws)

    async def handle_message(self, websocket: WebSocket, client_id: str, data: dict):
        """Handle incoming WebSocket messages."""
        msg_type = data.get("type")
        
        if msg_type == "subscribe":
            category = data.get("category", "all")
            # In a real implementation, you'd track subscriptions per connection
            await websocket.send_json({"type": "subscribed", "category": category})
            
        elif msg_type == "signal_request":
            condition_id = data.get("condition_id")
            if condition_id:
                await self._handle_signal_request(websocket, client_id, condition_id)
                
        elif msg_type == "scan_request":
            category = data.get("category", "fed-rate-decisions")
            top_k = data.get("top_k", 5)
            await self._handle_scan_request(websocket, client_id, category, top_k)
            
        elif msg_type == "ping":
            await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})

    async def _handle_signal_request(self, websocket: WebSocket, client_id: str, condition_id: str):
        """Handle a signal request for a specific market."""
        try:
            await websocket.send_json({"type": "processing", "condition_id": condition_id})
            
            engine = FusionEngine()
            signal = await engine.process_market(condition_id)
            await engine.close()
            
            response = {
                "type": "signal",
                "signal_id": signal.signal_id,
                "timestamp": signal.timestamp.isoformat(),
                "market_id": signal.market_id,
                "question": signal.question,
                "category": signal.category,
                "fused_probability_up": signal.fused_probability_up,
                "fused_confidence": signal.fused_confidence,
                "macro_signal_strength": signal.macro_signal_strength.value,
                "market_signal_strength": signal.market_signal_strength.value,
                "key_drivers": signal.key_drivers,
                "risk_factors": signal.risk_factors,
                "explainer_available": signal.explainer_script is not None,
            }
            
            await websocket.send_json({"type": "signal", "data": response})
            
        except Exception as e:
            await websocket.send_json({"type": "error", "message": str(e), "condition_id": condition_id})

    async def _handle_scan_request(self, websocket: WebSocket, client_id: str, category: str, top_k: int):
        """Handle a scan request for a category."""
        try:
            await websocket.send_json({"type": "scanning", "category": category})
            
            signals = await run_fusion_scan(category, top_k)
            
            response = {
                "type": "scan_results",
                "category": category,
                "scanned_at": datetime.now().isoformat(),
                "signals": [
                    {
                        "signal_id": s.signal_id,
                        "timestamp": s.timestamp.isoformat(),
                        "market_id": s.market_id,
                        "question": s.question,
                        "category": s.category,
                        "fused_probability_up": s.fused_probability_up,
                        "fused_confidence": s.fused_confidence,
                        "macro_signal_strength": s.macro_signal_strength.value,
                        "market_signal_strength": s.market_signal_strength.value,
                        "key_drivers": s.key_drivers,
                        "risk_factors": s.risk_factors,
                        "explainer_available": s.explainer_script is not None,
                    }
                    for s in signals
                ],
            }
            
            await websocket.send_json(response)
            
        except Exception as e:
            await websocket.send_json({"type": "error", "message": str(e), "category": category})

    async def start_periodic_scans(self):
        """Start periodic background scans for active categories."""
        categories = ["fed-rate-decisions", "cpi-inflation", "crypto-prices"]
        
        async def scan_loop():
            while True:
                try:
                    for category in categories:
                        signals = await run_fusion_scan(category, top_k=10)
                        await self.broadcast({
                            "type": "periodic_scan",
                            "category": category,
                            "scanned_at": datetime.now().isoformat(),
                            "signals": [
                                {
                                    "signal_id": s.signal_id,
                                    "timestamp": s.timestamp.isoformat(),
                                    "market_id": s.market_id,
                                    "question": s.question,
                                    "category": s.category,
                                    "fused_probability_up": s.fused_probability_up,
                                    "fused_confidence": s.fused_confidence,
                                    "macro_signal_strength": s.macro_signal_strength.value,
                                    "market_signal_strength": s.market_signal_strength.value,
                                    "key_drivers": s.key_drivers,
                                    "risk_factors": s.risk_factors,
                                }
                                for s in signals
                            ],
                        }, category=category)
                except Exception as e:
                    logger.error(f"Periodic scan failed: {e}")
                await asyncio.sleep(300)  # Every 5 minutes
        
        task = asyncio.create_task(scan_loop())
        self._scan_tasks["periodic_scans"] = task

    async def stop_periodic_scans(self):
        """Stop periodic background scans."""
        if "periodic_scans" in self._scan_tasks:
            self._scan_tasks["periodic_scans"].cancel()
            del self._scan_tasks["periodic_scans"]


class ConnectionManager:
    """Manages WebSocket connections for the FastAPI app."""

    def __init__(self):
        self.server = WebSocketServer()

    async def connect(self, websocket: WebSocket, client_id: str):
        await self.server.connect(websocket, client_id)

    def disconnect(self, websocket: WebSocket, client_id: str):
        self.server.disconnect(websocket, client_id)

    async def handle_websocket(self, websocket: WebSocket, client_id: str):
        """Main WebSocket handler loop."""
        await self.connect(websocket, client_id)
        try:
            while True:
                data = await websocket.receive_json()
                await self.server.handle_message(websocket, client_id, data)
        except WebSocketDisconnect:
            self.disconnect(websocket, client_id)
        except Exception as e:
            logger.error(f"WebSocket error for {client_id}: {e}")
            self.disconnect(websocket, client_id)


# Global connection manager
manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket, client_id: str = "default"):
    """FastAPI WebSocket endpoint."""
    await manager.handle_websocket(websocket, client_id)


def start_websocket_server():
    """Start the WebSocket server (as part of FastAPI app)."""
    # This is integrated into the FastAPI app via the websocket_endpoint
    pass