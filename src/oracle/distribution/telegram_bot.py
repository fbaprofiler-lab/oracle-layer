"""
Oracle Layer — Telegram Bot
Consumer-facing bot for daily signals and explainer delivery
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from ..core.config import settings
from ..fusion.engine import FusionEngine, run_fusion_scan

logger = logging.getLogger(__name__)


class OracleTelegramBot:
    """Telegram bot for Oracle Layer signals."""

    def __init__(self):
        self.token = settings.telegram_bot_token
        self.allowed_chats = set(settings.telegram_allowed_chat_ids)
        self.app = None
        self.fusion_engine = FusionEngine()

    async def start(self):
        """Start the bot."""
        if not self.token:
            logger.warning("TELEGRAM_BOT_TOKEN not set, skipping bot startup")
            return

        self.app = Application.builder().token(self.token).build()

        # Add handlers
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("signal", self.cmd_signal))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        self.app.add_handler(CommandHandler("categories", self.cmd_categories))
        self.app.add_handler(CommandHandler("explainer", self.cmd_explainer))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CallbackQueryHandler(self.callback_query))

        # Initialize and start
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Oracle Telegram bot started")

    async def stop(self):
        """Stop the bot."""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    def _is_allowed(self, chat_id: int) -> bool:
        """Check if chat is allowed."""
        return not self.allowed_chats or chat_id in self.allowed_chats

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        if not self._is_allowed(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized")
            return

        await update.message.reply_text(
            "🔮 **Oracle Layer** — Calibrated Prediction Market Intelligence\n\n"
            "Commands:\n"
            "• `/signal <market_id>` — Get fused signal for a market\n"
            "• `/scan [category]` — Scan category for top signals\n"
            "• `/categories` — List available categories\n"
            "• `/explainer <market_id>` — Get generative explainer\n"
            "• `/help` — Show this help\n\n"
            "Categories: fed-rate-decisions, cpi-inflation, crypto-prices, "
            "election-politics, climate-weather, tech-ai-milestones, "
            "geopolitics, earnings-economy",
            parse_mode="Markdown"
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await self.cmd_start(update, context)

    async def cmd_categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /categories command."""
        if not self._is_allowed(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized")
            return

        categories = [
            "🏦 `fed-rate-decisions` — Fed rate decisions & CPI",
            "📊 `cpi-inflation` — Inflation & CPI data",
            "₿ `crypto-prices` — Crypto price predictions",
            "🗳 `election-politics` — Political outcomes",
            "🌤 `climate-weather` — Weather & climate",
            "🤖 `tech-ai-milestones` — Tech/AI milestones",
            "🌍 `geopolitics` — Geopolitical events",
            "💰 `earnings-economy` — Earnings & economy",
        ]

        await update.message.reply_text(
            "**Available Categories:**\n\n" + "\n".join(categories),
            parse_mode="Markdown"
        )

    async def cmd_signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /signal command."""
        if not self._is_allowed(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized")
            return

        if not context.args:
            await update.message.reply_text("Usage: `/signal <market_id>`")
            return

        condition_id = context.args[0]
        await update.message.reply_text(f"🔍 Fetching signal for `{condition_id}`...")

        try:
            engine = FusionEngine()
            signal = await engine.process_market(condition_id)
            await engine.close()

            # Format signal response
            direction = "📈 UP" if signal.fused_probability_up > 0.5 else "📉 DOWN"
            prob_pct = round(signal.fused_probability_up * 100)

            text = (
                f"🔮 **Oracle Signal**\n\n"
                f"**Market:** {signal.question[:100]}\n"
                f"**Category:** {signal.category}\n"
                f"**Direction:** {direction} ({prob_pct}%)\n"
                f"**Confidence:** {round(signal.fused_confidence * 100)}%\n\n"
                f"**Key Drivers:**\n" + "\n".join(f"• {d}" for d in signal.key_drivers[:3]) + "\n\n"
                f"**Risk Factors:**\n" + "\n".join(f"• {r}" for r in signal.risk_factors[:3]) + "\n\n"
                f"**Macro Strength:** {signal.macro_signal_strength.value.title()}\n"
                f"**Market Strength:** {signal.market_signal_strength.value.title()}\n\n"
                f"`Signal ID: {signal.signal_id}`"
            )

            # Add inline keyboard for explainer
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🎬 Get Explainer", callback_data=f"explainer:{signal.market_id}")
            ]])

            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def cmd_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /scan command."""
        if not self._is_allowed(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized")
            return

        category = context.args[0] if context.args else "fed-rate-decisions"
        await update.message.reply_text(f"🔍 Scanning `{category}` for top signals...")

        try:
            signals = await run_fusion_scan(category, top_k=5)

            if not signals:
                await update.message.reply_text("No signals found.")
                return

            for i, signal in enumerate(signals, 1):
                direction = "📈 UP" if signal.fused_probability_up > 0.5 else "📉 DOWN"
                prob_pct = round(signal.fused_probability_up * 100)

                text = (
                    f"**{i}. {signal.question[:80]}**\n"
                    f"Direction: {direction} ({prob_pct}%) | "
                    f"Confidence: {round(signal.fused_confidence * 100)}%\n"
                    f"Drivers: {', '.join(signal.key_drivers[:2])}\n"
                    f"`{signal.signal_id}`"
                )

                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🎬 Explainer", callback_data=f"explainer:{signal.market_id}")
                ]])

                await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def cmd_explainer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /explainer command."""
        if not self._is_allowed(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized")
            return

        if not context.args:
            await update.message.reply_text("Usage: `/explainer <market_id>`")
            return

        condition_id = context.args[0]
        await update.message.reply_text(f"🎬 Generating explainer for `{condition_id}`...")

        try:
            engine = FusionEngine()
            signal = await engine.process_market(condition_id)
            await engine.close()

            if not signal.explainer_script:
                await update.message.reply_text("No explainer available for this signal.")
                return

            await update.message.reply_text(
                f"🎬 **Explainer Script** for `{signal.question[:80]}`\n\n"
                f"{signal.explainer_script.json()[:2000]}..."
            )

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard callbacks."""
        query = update.callback_query
        await query.answer()

        if not self._is_allowed(query.message.chat_id):
            await query.edit_message_text("❌ Unauthorized")
            return

        data = query.data
        if data.startswith("explainer:"):
            condition_id = data.split(":", 1)[1]
            await query.edit_message_text(f"🎬 Generating explainer for `{condition_id}`...")

            try:
                engine = FusionEngine()
                signal = await engine.process_market(condition_id)
                await engine.close()

                if not signal.explainer_script:
                    await query.edit_message_text("No explainer available for this signal.")
                    return

                await query.edit_message_text(
                    f"🎬 **Explainer Script**\n\n"
                    f"{signal.explainer_script.json()[:3000]}",
                    parse_mode="Markdown"
                )

            except Exception as e:
                await query.edit_message_text(f"❌ Error: {str(e)}")


# Convenience function
async def start_telegram_bot():
    """Start the Telegram bot."""
    bot = OracleTelegramBot()
    await bot.start()
    return bot