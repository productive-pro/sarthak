"""
Sarthak Spaces — Mastery engine.

Transform any directory into an expert-augmented learning environment.
Works for Data Scientists, Doctors, Teachers, Engineers, and anyone
who wants to master a skill faster than they thought possible.

Quick start:
    orch = SpacesOrchestrator("/path/to/workspace")
    result = await orch.next_session()
    print(result.reply)
"""
from sarthak.spaces.domain_loader import (
    get_available_projects,
    get_domain,
    get_next_concepts,
)
from sarthak.spaces.learner_context import (
    LearnerContext,
    build_learner_context,
    learner_context_for_prompt,
)
from sarthak.spaces.models import (
    ConceptMastery,
    LearnerProfile,
    LearningTask,
    MasteryResult,
    ProjectRecord,
    SkillLevel,
    SpaceContext,
    SpaceProfile,
    SpaceType,
    ToolRecommendation,
)
from sarthak.spaces.notes import (
    NoteRecord,
    image_to_note,
    load_all_notes,
    load_notes,
    notes_summary_for_context,
    take_concept_note,
)
from sarthak.spaces.orchestrator import SpacesOrchestrator
from sarthak.spaces.store import (
    get_active_space,
    get_space_context,
    init_space,
    init_space_profile,
    list_spaces,
    load_profile,
    load_space,
    save_profile,
    save_space,
    set_active_space,
    update_space,
)
from sarthak.spaces.workspace_transformer import WorkspaceTransformer

__all__ = [
    # Models
    "SpaceProfile", "SpaceContext", "LearnerProfile",
    "LearningTask", "MasteryResult", "SpaceType", "SkillLevel",
    "ConceptMastery", "ProjectRecord", "ToolRecommendation",
    # Orchestrator
    "SpacesOrchestrator",
    # Workspace structure
    "WorkspaceTransformer",
    # Store (space config + profile)
    "load_space", "save_space", "init_space", "update_space",
    "get_space_context", "list_spaces", "set_active_space", "get_active_space",
    "load_profile", "save_profile", "init_space_profile",
    # Domains
    "get_domain", "get_next_concepts", "get_available_projects",
    # Notes + OCR
    "image_to_note", "take_concept_note",
    "load_notes", "load_all_notes", "notes_summary_for_context", "NoteRecord",
    # Learner context
    "build_learner_context", "learner_context_for_prompt", "LearnerContext",
]
