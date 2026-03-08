"""
Sarthak AI package.

Public surface
--------------
  from sarthak.features.ai import get_agent
  from sarthak.features.ai import analyse_snapshot, generate_daily_summary
  from sarthak.features.ai import classify_activity, extract_concepts, analyze_activity
  from sarthak.features.ai import ask_orchestrator
"""
from sarthak.features.ai.agent import (  # noqa: F401
    get_agent,
    analyse_snapshot,
    generate_daily_summary,
    classify_activity,
    extract_concepts,
    analyze_activity,
    ask_orchestrator,
    AgentDeps,
    ChatDeps,
    OrchestratorDeps,
    SarthakResult,
    ChatResult,
    OrchestratorResult,
    ActivityClassification,
    ConceptExtraction,
    ActivityInsights,
)
