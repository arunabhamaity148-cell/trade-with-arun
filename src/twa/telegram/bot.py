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

import time
from typing import List

from twa.config import Settings
from twa.logging import get_logger
from twa.models.types import RegimeLabel, Side, SignalIdea

log = get_logger("telegram")

try:
    from telegram import Update, Bot
    from telegram.ext import Application, CommandHandler, ContextTypes
    _PTB_AVAILABLE = True
except Exception:  # pragma: no cover - optional runtime dep
    _PTB_AVAILABLE = False


def _md(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("`", "'")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("[", "(")
        .replace("]", ")")
    )


def render_signal(sig: SignalIdea) -> str:
    """Format a single signal idea for Telegram premium Markdown output."""
    SIDE_EMOJIS = {
        Side.LONG: ("🟢", "LONG"),
        Side.SHORT: ("🔴", "SHORT"),
        Side.NEUTRAL: ("⚪", "NEUTRAL"),
    }
    REGIME_EMOJIS = {
        RegimeLabel.TREND_UP: "🟢",
        RegimeLabel.TREND_DOWN: "🟣",
        RegimeLabel.RANGE: "🔵",
        RegimeLabel.VOLATILE: "🟡",
        RegimeLabel.STRESSED: "🟠",
    }
    CONFIDENCE_SEGMENTS = 10
    CONFIDENCE_FILLED = "█"
    CONFIDENCE_EMPTY = "░"
    MAX_FACTORS = 4
    MAX_NEWS = 2

    side_emoji, side_label = SIDE_EMOJIS[sig.side]
    regime_emoji = REGIME_EMOJIS.get(sig.regime, "⚪")
    filled = min(CONFIDENCE_SEGMENTS, int(sig.confidence * CONFIDENCE_SEGMENTS + 1e-9))
    bar = CONFIDENCE_FILLED * filled + CONFIDENCE_EMPTY * (CONFIDENCE_SEGMENTS - filled)
    conf_pct = sig.confidence * 100.0
    expiry = sig.expires_at.strftime("%Y-%m-%d %H:%M UTC") if sig.expires_at else "n/a"

    lines = [
        f"{side_emoji} *{_md(sig.symbol)}* · `{sig.timeframe.value}` · {regime_emoji} *{_md(sig.regime.value.upper())}*",
        f"*Bias* `{side_label}`   *Confidence* `{bar}` `{sig.confidence:.2f}` ({conf_pct:.1f}%)",
        "",
        f"*Entry zone* `{sig.entry_zone[0]:.6g}` → `{sig.entry_zone[1]:.6g}`",
        f"*TP1* `{sig.targets[0]:.6g}`   *TP2* `{sig.targets[1]:.6g}`   *TP3* `{sig.targets[2]:.6g}`",
        f"*Invalidation / SL* `{sig.invalidation:.6g}`",
        f"*Expected edge (bps)* `{sig.expected_edge_bps:+.1f}`",
        f"*News dampening* `{sig.news_dampen:.2f}`",
    ]

    if sig.rationale:
        lines.extend(["", "*Why now*"])
        for reason in sig.rationale[:3]:
            lines.append(f"• {_md(reason)}")

    contrib_lines = sorted(sig.factor_contributions, key=lambda c: -abs(c.contribution))
    if contrib_lines:
        lines.extend(["", "*Top factors*"])
        for c in contrib_lines[:MAX_FACTORS]:
            arrow = "📈" if c.contribution > 0 else ("📉" if c.contribution < 0 else "➖")
            lines.append(
                f"{arrow} `{_md(c.name)}` n `{c.norm_value:+.2f}` · w `{c.weight:+.2f}` · c `{c.contribution:+.3f}`"
            )

    if sig.news_events:
        lines.extend(["", "*News context*"])
        for ev in sig.news_events[:MAX_NEWS]:
            when = ev.published_at.strftime("%m-%d %H:%M UTC")
            lines.append(
                f"• `{ev.category}` sev `{ev.severity:.2f}` · {_md(ev.title[:100])} · `{when}`"
            )

    lines.extend([
        "",
        "⚠️ _Signal only — no orders are placed._",
        f"_Signal ID_ `{_md(sig.id)}`   _Expiry_ `{expiry}`",
    ])
    return "\n".join(lines)


def render_status(side: str, regime: str, conf: float, info_lines: List[str]) -> str:
    """Compact status block used by /health, /regime, /stats."""
    head = f"*{_md(side)}*  •  regime *{_md(regime)}*  •  confidence `{conf:.2f}`"
    return head + "\n\n" + "\n".join(f"  • {_md(l)}" for l in info_lines)


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
                f"  • `{n}` status={_md(h.get('status', 'n/a'))} err={_md(str(h.get('last_error')))} rate={h.get('recent_error_rate', 0.0):.2f}"
                for n, h in health.get("adapters", {}).items()
            )
            await update.message.reply_text(text or "(no data)", parse_mode="Markdown")

        async def cmd_config(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if not await _is_admin(update):
                return
            txt = ctx.application.bot_data.get("config_text", "(no config snapshot)")
            await update.message.reply_text(f"*Configuration*\n  {_md(txt)}", parse_mode="Markdown")

        app.add_handler(CommandHandler("signal", cmd_signal))
        app.add_handler(CommandHandler("health", cmd_health))
        app.add_handler(CommandHandler("config", cmd_config))

        log.info("telegram.command_loop.starting")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)  # type: ignore[attr-defined]

    async def stop(self) -> None:
        if self._app:
            try:
                await self._app.updater.stop_polling()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as e:  # noqa: BLE001
                log.debug("telegram.stop_failed", err=str(e))
