from dataclasses import dataclass, field
from typing import Optional
import time
import uuid


@dataclass
class MemoryUnit:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    summary: str = ""
    embedding: list[float] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    last_used: float = field(default_factory=time.time)
    prompt_fragment: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    access_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "summary": self.summary,
            "tags": self.tags,
            "importance": self.importance,
            "last_used": self.last_used,
            "prompt_fragment": self.prompt_fragment,
            "created_at": self.created_at,
            "access_count": self.access_count,
        }

    @classmethod
    def from_row(cls, row: dict) -> "MemoryUnit":
        import json

        return cls(
            id=row["id"],
            summary=row["summary"],
            tags=json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"],
            importance=row["importance"],
            last_used=row["last_used"],
            prompt_fragment=row["prompt_fragment"],
            created_at=row["created_at"],
            access_count=row["access_count"],
        )
