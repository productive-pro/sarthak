"""Orchestrator package — service supervisor + agent routing."""
from sarthak.features.ai.agent import ask_orchestrator as ask
from sarthak.features.ai.agent import ask_orchestrator as route  # compat alias
from sarthak.orchestrator.service import main

__all__ = ["route", "ask", "main"]
