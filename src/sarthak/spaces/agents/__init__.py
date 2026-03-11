from sarthak.spaces.agents._common import detect_platform, is_technical
from sarthak.spaces.agents.assessment import AssessmentAgent, QuickTestAgent
from sarthak.spaces.agents.content import EngagementAgent, MathAgent, ProjectAgent, TaskBuilderAgent
from sarthak.spaces.agents.curriculum import CurriculumAgent, OnboardingAgent
from sarthak.spaces.agents.gamification import BadgeAgent, SpacedRepetitionAgent
from sarthak.spaces.agents.workspace import (
    EnvironmentAgent,
    ExternalToolsAgent,
    WorkspaceAgent,
    WorkspaceAnalyserAgent,
)

__all__ = [
    "AssessmentAgent",
    "BadgeAgent",
    "CurriculumAgent",
    "EngagementAgent",
    "EnvironmentAgent",
    "ExternalToolsAgent",
    "MathAgent",
    "OnboardingAgent",
    "ProjectAgent",
    "QuickTestAgent",
    "SpacedRepetitionAgent",
    "TaskBuilderAgent",
    "WorkspaceAgent",
    "WorkspaceAnalyserAgent",
    "detect_platform",
    "is_technical",
]
