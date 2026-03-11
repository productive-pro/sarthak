from sarthak.web.routers.activity import router as activity_router
from sarthak.web.routers.agents import router as agents_router
from sarthak.web.routers.chat import router as chat_router
from sarthak.web.routers.config import router as config_router
from sarthak.web.routers.dashboard import router as dashboard_router
from sarthak.web.routers.spaces import router as spaces_router
from sarthak.web.routers.spa import router as spa_router
from sarthak.web.routers.spa import REACT_DIST

__all__ = [
    "activity_router",
    "agents_router",
    "chat_router",
    "config_router",
    "dashboard_router",
    "spaces_router",
    "spa_router",
    "REACT_DIST",
]
