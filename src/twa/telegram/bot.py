"""Telegram premium experience.

Commands (admin chat only unless stated):
  /signal          → current open trade ideas for the watchlist
  /config          → current effective configuration
  /health          → feed + adapter health summary
  /regime          → current market regime classification
  /stats           → per-symbol signal statistics (last 24h)
  /symbols         → list watched symbols
  /sym SYMBOL TF   → manual refresh for a symbol (admin)

The bot NEVER sends orders.  All messages are informational.
"""
from __future__ import annotations

import asyncio
import time
from typing import List, Optional

from twa.config import Settings
from twa.logging import get_logger
from twa.models.types import SignalIdea

log = get_logger("telegram")

try:
    from telegram import Update, Bot
    from telegram.ext import Application, CommandHandler, ContextTypes
    _PTB_AVAILABLE = True
except Exception:  # pragma: no cover - optional runtime dep
    _PTB_AVAILABLE = False


# -----------------------------------------------------------------------------
# Premium rendering
# -----------------------------------------------------------------------------
def render_signal(sig: SignalIdea) -> str:
    """Format a single signal idea for Telegram.  No HTML / Markdown ambiguity."""
    conf_pct = int(round(sig.confidence * 100))
    fire = "🟢" if sig.confidence >= 0.7 else ("🟡" if sig.confidence >= 0.45 else "🟠")
    bar = "▓" * (conf_pct // 10) + "░" * (10 - conf_pct // 10)
    direction = "🟢 LONG" if sig.side.value == "LONG" else ("🔴 SHORT" if sig.side.value == "SHORT" else "⚪ NEUTRAL")
    lines = [
        f"{fire} *{sig.symbol}*  •  *{sig.timeframe.value}*  •  *{sig.regime.value.upper()}*",
        f"{direction}        (confidence `{bar}` {conf_pct}%)",
        "",
        f"*Entry zone*   : `{sig.entry_zone[0]:.6g}`  —  `{sig.entry_zone[1]:.6g}`",
        f"*Targets*      : 1R `{sig.targets[0]:.6g}`  •  2R `{sig.targets[1]:.6g}`  •  3R `{sig.targets[2]:.6g}`",
        f"*Invalidation* : `{sig.invalidation:.6g}`",
        f"*Expected edge*: `{sig.expected_edge_bps:+.1f}` bps",
        f"*News dampen* : `{sig.news_dampen:.2f}`",
        "",
        "*Why:*",
    ]
    for r in sig.rationale:
        lines.append(f"  • {r}")
    contrib_lines = sorted(sig.factor_contributions, key=lambda c: -abs(c.contribution))
    if contrib_lines:
        lines.append("")
        lines.append("*Top factors* (weight · normalised · contribution):")
        for c in contrib_lines[:5]:
            lines.append(
                f"  • `{c.name}`  w `{c.weight:+.2f}`  n `{c.norm_value:+.2f}`  →  `{c.contribution:+.3f}`"
            )
    if sig.news_events:
        lines.append("")
        lines.append("*News events* impacting confidence:")
        for ev in sig.news_events[:3]:
            when = ev.published_at.strftime("%Y-%m-%d %H:%M UTC")
            lines.append(f"  • [{ev.category}|{ev.severity:.2f}] {ev.title[:120]} ({when})")
    lines.append("")
    lines.append("⚠️ _Signal only — no orders are placed._  ")
    lines.append(f"_Signal ID: `{sig.id}` · expires at {(sig.expires_at.strftime('%H:%M:%S UTC') if sig.expires_at else 'n/a')}_")
    return "\n".join(lines)


def render_status(side: str, regime: str, conf: float, info_lines: List[str]) -> str:
    """Compact status block used by /health, /regime, /stats."""
    head = f"*{side}*  •  regime *{regime}*  •  confidence `{conf:.2f}`"
    return head + "\n\n" + "\n".join(f"  • {l}" for l in info_lines)


# -----------------------------------------------------------------------------
# Bot runtime
# -----------------------------------------------------------------------------
class TelegramBot:
    """Optional Telegram bot.  No-op if not configured or python-telegram-bot missing."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.enabled = bool(
            settings.telegram_enabled
            and settings.telegram_bot_token
            and settings.telegram_chat_id
            and _PTB_AVAILABLE
        )
        self._last_sent: float = 0.0
        self._app = None

    def _cooldown_ok(self) -> bool:
        return (time.time() - self._last_sent) >= self.settings.telegram_min_interval_s

    async def send_signal(self, sig: SignalIdea) -> bool:
        if not self.enabled:
            return False
        if not self._cooldown_ok():
            log.debug("telegram.cooldown", symbol=sig.symbol)
            return False
        text = render_signal(sig)
        try:
            bot: Bot = self._app.bot if self._app else Bot(self.settings.telegram_bot_token)
            await bot.send_message(
                chat_id=self.settings.telegram_chat_id,
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            self._last_sent = time.time()
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("telegram.send_failed", err=str(e))
            return False

    async def send_text(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            bot: Bot = self._app.bot if self._app else Bot(self.settings.telegram_bot_token)
            await bot.send_message(
                chat_id=self.settings.telegram_chat_id, text=text,
                parse_mode="Markdown", disable_web_page_preview=True,
            )
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("telegram.send_failed", err=str(e))
            return False

    async def start_command_loop(self) -> None:
        """Spawn the command handler loop (admin only)."""
        if not self.enabled:
            log.info("telegram.disabled")
            return
        app = Application.builder().token(self.settings.telegram_bot_token).build()
        self._app = app

        chat_id = self.settings.telegram_chat_id

        async def _is_admin(update: Update) -> bool:
            return str(update.effective_chat.id) == str(chat_id)

        async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if not await _is_admin(update):
                return
            sigs: List[SignalIdea] = ctx.application.bot_data.get("signals", [])
            if not sigs:
                await update.message.reply_text("No active signals.")
                return
            for s in sigs[-5:]:
                await update.message.reply_text(render_signal(s), parse_mode="Markdown")

        async def cmd_health(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if not await _is_admin(update):
                return
            health = ctx.application.bot_data.get("health", {})
            text = "*Health*\n" + "\n".join(
                f"  • `{n}` last_ok={h.get('last_ok_ts')} err={h.get('last_error')}"
                for n, h in health.get("adapters", {}).items()
            )
            await update.message.reply_text(text or "(no data)", parse_mode="Markdown")

        async def cmd_config(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if not await _is_admin(update):
                return
            txt = ctx.application.bot_data.get("config_text", "(no config snapshot)")
            await update.message.reply_text(f"*Configuration*\n  {txt}", parse_mode="Markdown")

        app.add_handler(CommandHandler("signal", cmd_signal))
        app.add_handler(CommandHandler("health", cmd_health))
        app.add_handler(CommandHandler("config", cmd_config))

        log.info("telegram.command_loop.starting")
        await app.initialize()
        await app.start()
        # run polling in background
        await app.updater.start_polling(drop_pending_updates=True)  # type: ignore[attr-defined]

    async def stop(self) -> None:
        if self._app:
            try:
                await self._app.updater.stop_polling()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as e:  # noqa: BLE001
                log.debug("telegram.stop_failed", err=str(e))
