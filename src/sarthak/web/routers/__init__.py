from sarthak.web.routers.activity import router as activity_router
from sarthak.web.routers.agents import router as agents_router
from sarthak.web.routers.chat import router as chat_router
from sarthak.web.routers.config import router as config_router
from sarthak.web.routers.dashboard import router as dashboard_router
from sarthak.web.routers.spaces import router as spaces_router
from sarthak.web.routers.spaces_rag import router as spaces_rag_router
from sarthak.web.routers.spaces_practice import router as spaces_practice_router
from sarthak.web.routers.spaces_settings import router as spaces_settings_router
from sarthak.web.routers.spa import router as spa_router
from sarthak.web.routers.spa import REACT_DIST

__all__ = [
    "activity_router",
    "agents_router",
    "chat_router",
    "config_router",
    "dashboard_router",
    "spaces_router",
    "spaces_rag_router",
    "spaces_practice_router",
    "spaces_settings_router",
    "spa_router",
    "REACT_DIST",
]
