"""Token-window chunking service for large artifacts."""

import logging
import hashlib
from typing import List, Tuple

import tiktoken

from storage.models import Chunk


logger = logging.getLogger("mcp-memory.chunking")


class ChunkingService:
    """Token-window chunking for large artifacts."""

    def __init__(
        self,
        single_piece_max: int = 1200,
        chunk_target: int = 900,
        chunk_overlap: int = 100
    ):
        """
        Initialize chunking service.

        Args:
            single_piece_max: Threshold for chunking (tokens)
            chunk_target: Target chunk size (tokens)
            chunk_overlap: Overlap between chunks (tokens)
        """
        self.single_piece_max = single_piece_max
        self.chunk_target = chunk_target
        self.chunk_overlap = chunk_overlap
        self.encoding = tiktoken.get_encoding("cl100k_base")

    def should_chunk(self, text: str) -> Tuple[bool, int]:
        """
        Determine if text needs chunking.

        Args:
            text: Text to evaluate

        Returns:
            Tuple of (should_chunk, token_count)
        """
        tokens = self.encoding.encode(text)
        token_count = len(tokens)
        should_chunk = token_count > self.single_piece_max

        logger.debug(
            f"Chunk decision: token_count={token_count}, "
            f"threshold={self.single_piece_max}, will_chunk={should_chunk}"
        )

        return should_chunk, token_count

    def chunk_text(self, text: str, artifact_id: str) -> List[Chunk]:
        """
        Chunk text using token-window strategy.

        Args:
            text: Text to chunk
            artifact_id: Parent artifact ID

        Returns:
            List of Chunk objects (empty if text ≤ threshold)
        """
        # Check if chunking needed
        should_chunk, token_count = self.should_chunk(text)
        if not should_chunk:
            return []

        # Tokenize
        tokens = self.encoding.encode(text)
        chunks = []
        pos = 0
        chunk_index = 0

        while pos < len(tokens):
            # Extract chunk tokens
            chunk_tokens = tokens[pos : pos + self.chunk_target]
            chunk_text = self.encoding.decode(chunk_tokens)

            # Compute character offsets
            start_char = len(self.encoding.decode(tokens[:pos]))
            end_char = start_char + len(chunk_text)

            # Generate stable chunk ID
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()
            chunk_id = f"{artifact_id}::chunk::{chunk_index:03d}::{content_hash[:8]}"

            # Create chunk
            chunk = Chunk(
                chunk_id=chunk_id,
                artifact_id=artifact_id,
                chunk_index=chunk_index,
                content=chunk_text,
                start_char=start_char,
                end_char=end_char,
                token_count=len(chunk_tokens),
                content_hash=content_hash
            )
            chunks.append(chunk)

            # Advance with overlap
            pos += self.chunk_target - self.chunk_overlap
            chunk_index += 1

        avg_chunk_size = sum(c.token_count for c in chunks) / len(chunks) if chunks else 0

        logger.info(
            f"Text chunked: artifact_id={artifact_id}, "
            f"total_tokens={token_count}, num_chunks={len(chunks)}, "
            f"avg_chunk_size={avg_chunk_size:.0f}, overlap={self.chunk_overlap}"
        )

        return chunks

    def expand_chunk_neighbors(
        self,
        artifact_id: str,
        chunk_index: int,
        all_chunks: List[Chunk]
    ) -> str:
        """
        Get chunk with ±1 neighbors and [CHUNK BOUNDARY] markers.

        Args:
            artifact_id: Artifact ID
            chunk_index: Index of target chunk
            all_chunks: All chunks for artifact (sorted by chunk_index)

        Returns:
            Combined text with [CHUNK BOUNDARY] markers
        """
        if not all_chunks:
            return ""

        # Find target chunk
        target = None
        for chunk in all_chunks:
            if chunk.chunk_index == chunk_index:
                target = chunk
                break

        if target is None:
            logger.warning(
                f"Chunk index {chunk_index} not found for artifact {artifact_id}"
            )
            return ""

        # Find neighbors
        prev_chunk = None
        next_chunk = None

        if chunk_index > 0:
            for chunk in all_chunks:
                if chunk.chunk_index == chunk_index - 1:
                    prev_chunk = chunk
                    break

        if chunk_index < len(all_chunks) - 1:
            for chunk in all_chunks:
                if chunk.chunk_index == chunk_index + 1:
                    next_chunk = chunk
                    break

        # Build combined text
        parts = []

        if prev_chunk:
            parts.append(prev_chunk.content)
            parts.append("[CHUNK BOUNDARY]")

        parts.append(target.content)

        if next_chunk:
            parts.append("[CHUNK BOUNDARY]")
            parts.append(next_chunk.content)

        return "\n".join(parts)

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text using tiktoken.

        Args:
            text: Text to count

        Returns:
            Number of tokens
        """
        tokens = self.encoding.encode(text)
        return len(tokens)
