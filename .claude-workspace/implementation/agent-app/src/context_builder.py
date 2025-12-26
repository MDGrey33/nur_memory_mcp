"""
Context assembly from history and memory sources.

Fetches data via gateway and assembles context for LLM prompts.
No storage decisions - pure assembly logic.
"""

import asyncio
import logging
from typing import Optional

try:
    from .memory_gateway import ChromaMcpGateway
    from .models import HistoryTurn, MemoryItem, ContextPackage
    from .exceptions import ContextBuildError
    from .utils import count_tokens
except ImportError:
    # Support both relative and absolute imports
    from memory_gateway import ChromaMcpGateway
    from models import HistoryTurn, MemoryItem, ContextPackage
    from exceptions import ContextBuildError
    from utils import count_tokens


logger = logging.getLogger('mcp_memory.context_builder')


class ContextBuilder:
    """
    Assembles context from history and memory for LLM prompts.

    Fetches data in parallel, handles token budgets, and formats for consumption.
    """

    def __init__(
        self,
        gateway: ChromaMcpGateway,
        history_tail_n: int = 16,
        memory_top_k: int = 8,
        min_confidence: float = 0.7,
        token_budget: Optional[int] = None
    ):
        """
        Initialize context builder.

        Args:
            gateway: Memory gateway instance
            history_tail_n: Number of history turns to retrieve
            memory_top_k: Number of memories to retrieve
            min_confidence: Minimum memory confidence threshold
            token_budget: Optional token limit for context

        Raises:
            ValueError: If parameters are invalid
        """
        if history_tail_n < 1:
            raise ValueError(f"history_tail_n must be >= 1, got {history_tail_n}")
        if memory_top_k < 1:
            raise ValueError(f"memory_top_k must be >= 1, got {memory_top_k}")
        if not (0.0 <= min_confidence <= 1.0):
            raise ValueError(f"min_confidence must be in [0.0, 1.0], got {min_confidence}")
        if token_budget is not None and token_budget < 1:
            raise ValueError(f"token_budget must be >= 1 or None, got {token_budget}")

        self.gateway = gateway
        self.history_tail_n = history_tail_n
        self.memory_top_k = memory_top_k
        self.min_confidence = min_confidence
        self.token_budget = token_budget

        logger.info(f"ContextBuilder initialized: history_tail_n={history_tail_n}, "
                   f"memory_top_k={memory_top_k}, min_confidence={min_confidence}, "
                   f"token_budget={token_budget}")

    async def build_context(
        self,
        conversation_id: str,
        latest_user_text: str
    ) -> ContextPackage:
        """
        Build complete context for LLM response generation.

        Fetches history and memories in parallel for optimal performance.

        Args:
            conversation_id: Conversation identifier
            latest_user_text: Current user message text

        Returns:
            ContextPackage containing history, memories, and metadata

        Raises:
            ContextBuildError: If context assembly fails
        """
        logger.debug(f"Building context for conversation: {conversation_id}")

        try:
            # Parallel fetch for optimal latency
            history_task = self.gateway.tail_history(conversation_id, self.history_tail_n)
            memory_task = self.gateway.recall_memory(
                latest_user_text,
                self.memory_top_k,
                self.min_confidence,
                conversation_id=None  # Don't filter by conversation for broader recall
            )

            # Wait for both
            history_results, memory_results = await asyncio.gather(
                history_task,
                memory_task,
                return_exceptions=True
            )

            # Handle errors
            if isinstance(history_results, Exception):
                logger.warning(f"History fetch failed: {history_results}. Using empty history.")
                history_results = []

            if isinstance(memory_results, Exception):
                logger.warning(f"Memory recall failed: {memory_results}. Using empty memories.")
                memory_results = []

            # Transform to domain models
            history = self._parse_history(history_results)
            memories = self._parse_memories(memory_results)

            # Assemble context
            context = ContextPackage(
                history=history,
                memories=memories,
                latest_message=latest_user_text,
                metadata={
                    "history_count": len(history),
                    "memory_count": len(memories),
                    "truncated": False,
                    "total_tokens": 0
                }
            )

            # Apply token budget if set
            if self.token_budget:
                context = self._truncate_to_budget(context)

            # Calculate final token count
            context.metadata["total_tokens"] = self._count_context_tokens(context)

            logger.info(f"Context built: {len(history)} history turns, {len(memories)} memories, "
                       f"{context.metadata['total_tokens']} tokens")

            return context

        except Exception as e:
            logger.error(f"Context build failed: {e}")
            raise ContextBuildError(f"Failed to build context: {e}") from e

    def format_for_prompt(self, context: ContextPackage) -> str:
        """
        Format context dictionary as string for LLM prompt.

        Args:
            context: Context dictionary from build_context()

        Returns:
            Formatted string ready for prompt injection
        """
        parts = []

        # History section
        if context.history:
            parts.append("=== Recent Conversation History ===")
            parts.append(self._format_history(context.history))
            parts.append("")

        # Memories section
        if context.memories:
            parts.append("=== Relevant Memories ===")
            parts.append(self._format_memories(context.memories))
            parts.append("")

        # Current message
        parts.append("=== Current Message ===")
        parts.append(f"User: {context.latest_message}")

        return "\n".join(parts)

    def _parse_history(self, results: list[dict]) -> list[HistoryTurn]:
        """
        Parse raw history results into HistoryTurn objects.

        Args:
            results: Raw results from gateway

        Returns:
            List of HistoryTurn objects
        """
        history = []
        for result in results:
            try:
                metadata = result.get("metadata", {})
                turn = HistoryTurn(
                    conversation_id=metadata.get("conversation_id", ""),
                    role=metadata.get("role", "user"),
                    text=result.get("document", ""),
                    turn_index=metadata.get("turn_index", 0),
                    ts=metadata.get("ts", ""),
                    message_id=metadata.get("message_id"),
                    channel=metadata.get("channel")
                )
                history.append(turn)
            except Exception as e:
                logger.warning(f"Failed to parse history turn: {e}")
                continue

        return history

    def _parse_memories(self, results: list[dict]) -> list[tuple[MemoryItem, float]]:
        """
        Parse raw memory results into (MemoryItem, score) tuples.

        Args:
            results: Raw results from gateway

        Returns:
            List of (MemoryItem, similarity_score) tuples
        """
        memories = []
        for result in results:
            try:
                metadata = result.get("metadata", {})
                distance = result.get("distance", 1.0)

                # Convert distance to similarity score (lower distance = higher similarity)
                similarity = 1.0 - min(distance, 1.0)

                memory = MemoryItem(
                    text=result.get("document", ""),
                    memory_type=metadata.get("type", "fact"),
                    confidence=metadata.get("confidence", 0.0),
                    ts=metadata.get("ts", ""),
                    conversation_id=metadata.get("conversation_id"),
                    entities=metadata.get("entities"),
                    source=metadata.get("source"),
                    tags=metadata.get("tags")
                )
                memories.append((memory, similarity))
            except Exception as e:
                logger.warning(f"Failed to parse memory item: {e}")
                continue

        return memories

    def _format_history(self, history: list[HistoryTurn]) -> str:
        """
        Format history turns as readable text.

        Args:
            history: List of history turns

        Returns:
            Formatted history string
        """
        lines = []
        for turn in history:
            role_label = turn.role.capitalize()
            lines.append(f"[{turn.turn_index}] {role_label}: {turn.text}")
        return "\n".join(lines)

    def _format_memories(self, memories: list[tuple[MemoryItem, float]]) -> str:
        """
        Format memories as readable text.

        Args:
            memories: List of (MemoryItem, similarity_score) tuples

        Returns:
            Formatted memories string
        """
        lines = []
        for memory, score in memories:
            lines.append(f"- [{memory.memory_type}, confidence: {memory.confidence:.2f}, "
                        f"relevance: {score:.2f}] {memory.text}")
        return "\n".join(lines)

    def _truncate_to_budget(self, context: ContextPackage) -> ContextPackage:
        """
        Truncate context to fit token budget.

        Priority: latest_message > history > memories

        Args:
            context: Context to truncate

        Returns:
            Truncated context with truncated flag set
        """
        if not self.token_budget:
            return context

        # Calculate current token count
        total_tokens = self._count_context_tokens(context)

        if total_tokens <= self.token_budget:
            return context  # No truncation needed

        logger.debug(f"Truncating context: {total_tokens} tokens > budget {self.token_budget}")

        # Always keep latest message
        message_tokens = count_tokens(context.latest_message)
        remaining_budget = self.token_budget - message_tokens

        if remaining_budget <= 0:
            # Even the message is too large, just truncate it
            logger.warning("Latest message exceeds token budget")
            context.history = []
            context.memories = []
            context.metadata["truncated"] = True
            return context

        # Allocate budget: 60% history, 40% memories
        history_budget = int(remaining_budget * 0.6)
        memory_budget = remaining_budget - history_budget

        # Truncate history (keep most recent that fit)
        truncated_history = []
        history_tokens = 0
        for turn in reversed(context.history):
            turn_tokens = count_tokens(turn.text)
            if history_tokens + turn_tokens <= history_budget:
                truncated_history.insert(0, turn)
                history_tokens += turn_tokens
            else:
                break

        # Truncate memories (keep top-K that fit)
        truncated_memories = []
        memory_tokens = 0
        for memory, score in context.memories:
            mem_tokens = count_tokens(memory.text)
            if memory_tokens + mem_tokens <= memory_budget:
                truncated_memories.append((memory, score))
                memory_tokens += mem_tokens
            else:
                break

        context.history = truncated_history
        context.memories = truncated_memories
        context.metadata["truncated"] = True
        context.metadata["original_history_count"] = context.metadata["history_count"]
        context.metadata["original_memory_count"] = context.metadata["memory_count"]
        context.metadata["history_count"] = len(truncated_history)
        context.metadata["memory_count"] = len(truncated_memories)

        logger.info(f"Context truncated to {self._count_context_tokens(context)} tokens")

        return context

    def _count_context_tokens(self, context: ContextPackage) -> int:
        """
        Count total tokens in context.

        Args:
            context: Context to count

        Returns:
            Total token count
        """
        total = count_tokens(context.latest_message)

        for turn in context.history:
            total += count_tokens(turn.text)

        for memory, _ in context.memories:
            total += count_tokens(memory.text)

        return total
