"""WhatsApp channel for Sarthak AI — neonize QR-login bot.

Public API
----------
  SESSION_DB          path to the neonize SQLite session store
  SESSION_NAME        str(SESSION_DB), passed to NewClient
  send_message_standalone(text)  push a message to the configured JID (used by agents)
  is_connected()      True when the neonize bot is live

The bot lifecycle (start / stop) is managed by orchestrator/service.py via
  neonize_bot.start_neonize_bot() / stop_neonize_bot().

The QR-login web routes (/api/channels/whatsapp/qr|status|logout) are
  served by qr.py and mounted in web/app.py.
"""
from pathlib import Path
from platformdirs import user_data_dir

# ── Shared neonize session path ───────────────────────────────────────────────
# Single source of truth — neonize_bot, qr.py, and the configure wizard all
# import SESSION_DB / SESSION_NAME from here so they always share the same store.
SESSION_DB: Path = Path(user_data_dir("sarthak", "sarthak")) / "whatsapp_session.db"
SESSION_DB.parent.mkdir(parents=True, exist_ok=True)
SESSION_NAME: str = str(SESSION_DB)


# ── Lazy re-exports — keep startup fast; neonize import only on first use ─────

def send_message_standalone(text: str):
    """Async: send text to the configured JID. No-op if bot is not connected."""
    from sarthak.features.channels.whatsapp.neonize_bot import (
        send_message_standalone as _send,
    )
    return _send(text)


def is_connected() -> bool:
    """True when the neonize bot has an active connection."""
    try:
        from sarthak.features.channels.whatsapp.neonize_bot import is_connected as _ic
        return _ic()
    except Exception:
        return False


__all__ = ["SESSION_DB", "SESSION_NAME", "send_message_standalone", "is_connected"]
