"""
Extensible pipeline for requirement analysis and future codegen tasks.

Current stage: simple structured outline. Later stages may emit extension
scaffolding tasks (models, admin menus) or delegate to external agent tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AnalysisStage:
    name: str
    description: str


PIPELINE_STAGES: tuple[AnalysisStage, ...] = (
    AnalysisStage("summary", "High-level restatement of the request"),
    AnalysisStage("entities", "Candidate domain entities and relationships"),
    AnalysisStage("api_surface", "Suggested API or admin surfaces"),
    AnalysisStage("risks", "Risks, unknowns, and follow-up questions"),
)


def build_placeholder_tasks(user_text: str) -> list[dict[str, Any]]:
    """Future: map analysis to concrete extension tasks (models, menus, etc.)."""
    return [
        {
            "type": "placeholder",
            "message": "Codegen hooks not wired yet; extend pipeline.emit_tasks().",
            "input_preview": user_text[:200],
        }
    ]
