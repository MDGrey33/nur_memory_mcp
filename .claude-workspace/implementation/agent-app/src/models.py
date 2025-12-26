"""
Data models and validation.

All models use Python dataclasses with type hints.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class HistoryTurn:
    """A single conversation turn in history."""

    conversation_id: str
    role: str  # "user" | "assistant" | "system"
    text: str
    turn_index: int
    ts: str  # ISO-8601
    message_id: Optional[str] = None
    channel: Optional[str] = None

    def validate(self) -> None:
        """
        Validate turn data.

        Raises:
            ValueError: If validation fails
        """
        if not self.conversation_id:
            raise ValueError("conversation_id cannot be empty")

        if self.role not in ["user", "assistant", "system"]:
            raise ValueError(f"role must be one of [user, assistant, system], got {self.role}")

        if not self.text:
            raise ValueError("text cannot be empty")

        if len(self.text) > 100000:
            raise ValueError(f"text too long ({len(self.text)} chars), max 100,000")

        if self.turn_index < 0:
            raise ValueError(f"turn_index must be non-negative, got {self.turn_index}")

        # Validate ISO-8601 timestamp
        try:
            datetime.fromisoformat(self.ts.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            raise ValueError(f"ts must be valid ISO-8601 timestamp, got {self.ts}")

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "conversation_id": self.conversation_id,
            "role": self.role,
            "text": self.text,
            "turn_index": self.turn_index,
            "ts": self.ts,
            "message_id": self.message_id,
            "channel": self.channel
        }


@dataclass
class MemoryItem:
    """A long-term memory item."""

    text: str
    memory_type: str  # "preference" | "fact" | "project" | "decision"
    confidence: float  # [0.0, 1.0]
    ts: str  # ISO-8601
    conversation_id: Optional[str] = None
    entities: Optional[str] = None  # comma-separated
    source: Optional[str] = None  # "chat" | "tool" | "import"
    tags: Optional[str] = None  # comma-separated

    def validate(self) -> None:
        """
        Validate memory data.

        Raises:
            ValueError: If validation fails
        """
        if not self.text:
            raise ValueError("text cannot be empty")

        if len(self.text) > 2000:
            raise ValueError(f"text too long ({len(self.text)} chars), max 2,000. Summarize first.")

        valid_types = ["preference", "fact", "project", "decision"]
        if self.memory_type not in valid_types:
            raise ValueError(f"memory_type must be one of {valid_types}, got {self.memory_type}")

        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")

        # Validate ISO-8601 timestamp
        try:
            datetime.fromisoformat(self.ts.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            raise ValueError(f"ts must be valid ISO-8601 timestamp, got {self.ts}")

        if self.source and self.source not in ["chat", "tool", "import"]:
            raise ValueError(f"source must be one of [chat, tool, import], got {self.source}")

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "text": self.text,
            "type": self.memory_type,
            "confidence": self.confidence,
            "ts": self.ts,
            "conversation_id": self.conversation_id,
            "entities": self.entities,
            "source": self.source,
            "tags": self.tags
        }


@dataclass
class ContextPackage:
    """Complete context package for LLM prompt."""

    history: list[HistoryTurn]
    memories: list[tuple[MemoryItem, float]]  # (item, similarity_score)
    latest_message: str
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        """Initialize metadata defaults."""
        if not self.metadata:
            self.metadata = {
                "history_count": len(self.history),
                "memory_count": len(self.memories),
                "truncated": False,
                "total_tokens": 0
            }
