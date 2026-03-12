"""WhatsApp channel for Sarthak AI — Meta Cloud API webhook + neonize QR bot."""
from pathlib import Path
from platformdirs import user_data_dir

from .bot import router
from .client import send_message, send_message_standalone

# ── Shared neonize session path (used by configure wizard, QR endpoint, and bot) ──
# Single source of truth — all callers import from here.
SESSION_DB: Path = Path(user_data_dir("sarthak", "sarthak")) / "whatsapp_session.db"
SESSION_DB.parent.mkdir(parents=True, exist_ok=True)
SESSION_NAME: str = str(SESSION_DB)

# neonize_bot is imported lazily by the orchestrator service — not here,
# so missing neonize package doesn't break startup.
__all__ = ["router", "send_message", "send_message_standalone", "SESSION_DB", "SESSION_NAME"]
