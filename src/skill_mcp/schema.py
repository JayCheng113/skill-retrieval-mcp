"""Unified skill data model for all sources."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SkillSource(str, Enum):
    """Origin of a skill."""

    LANGSKILLS = "langskills"
    SKILLNET = "skillnet"
    ANTHROPIC = "anthropic"
    COMMUNITY = "community"


@dataclass
class Skill:
    """Unified representation of an agent skill from any source."""

    name: str
    description: str
    instructions: str
    source: SkillSource
    source_id: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = hashlib.md5(self.instructions.encode()).hexdigest()
        if not self.id:
            raw = f"{self.source.value}:{self.name}:{self.content_hash[:8]}"
            self.id = hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_embedding_text(self) -> str:
        """Text used for embedding: name + description + first 500 chars of instructions."""
        parts = [self.name, self.description]
        if self.instructions:
            parts.append(self.instructions[:500])
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "source": self.source.value,
            "source_id": self.source_id,
            "category": self.category,
            "tags": self.tags,
            "metadata": self.metadata,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        data = dict(data)
        data["source"] = SkillSource(data["source"])
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("tags"), str):
            import json
            data["tags"] = json.loads(data["tags"])
        if isinstance(data.get("metadata"), str):
            import json
            data["metadata"] = json.loads(data["metadata"])
        return cls(**data)


@dataclass
class RetrievedSkill:
    """A skill returned by a retrieval method with its score."""

    skill: Skill
    score: float
    retrieval_metadata: dict[str, Any] = field(default_factory=dict)
