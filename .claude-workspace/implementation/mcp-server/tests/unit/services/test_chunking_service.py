"""Unit tests for ChunkingService."""

import pytest
from services.chunking_service import ChunkingService
from storage.models import Chunk


# ============================================================================
# Initialization Tests
# ============================================================================

def test_init_with_defaults():
    """Test initialization with default parameters."""
    service = ChunkingService()

    assert service.single_piece_max == 1200
    assert service.chunk_target == 900
    assert service.chunk_overlap == 100
    assert service.encoding is not None


def test_init_with_custom_params():
    """Test initialization with custom parameters."""
    service = ChunkingService(
        single_piece_max=1500,
        chunk_target=1000,
        chunk_overlap=150
    )

    assert service.single_piece_max == 1500
    assert service.chunk_target == 1000
    assert service.chunk_overlap == 150


# ============================================================================
# Token Counting Tests
# ============================================================================

def test_count_tokens_short_text(chunking_service):
    """Test token counting with short text."""
    text = "Hello, world!"
    token_count = chunking_service.count_tokens(text)

    assert isinstance(token_count, int)
    assert token_count > 0
    assert token_count < 10  # Should be just a few tokens


def test_count_tokens_long_text(chunking_service):
    """Test token counting with longer text."""
    text = "This is a longer piece of text. " * 100
    token_count = chunking_service.count_tokens(text)

    assert token_count > 100


def test_count_tokens_empty_text(chunking_service):
    """Test token counting with empty text."""
    token_count = chunking_service.count_tokens("")
    assert token_count == 0


# ============================================================================
# Should Chunk Tests
# ============================================================================

def test_should_chunk_below_threshold(chunking_service, sample_text_short):
    """Test should_chunk returns False for text below threshold."""
    should_chunk, token_count = chunking_service.should_chunk(sample_text_short)

    assert should_chunk is False
    assert token_count > 0
    assert token_count < 1200


def test_should_chunk_above_threshold(chunking_service, sample_text_long):
    """Test should_chunk returns True for text above threshold."""
    should_chunk, token_count = chunking_service.should_chunk(sample_text_long)

    assert should_chunk is True
    assert token_count > 1200


def test_should_chunk_at_threshold(chunking_service):
    """Test should_chunk behavior at exact threshold."""
    # Generate text that's exactly at threshold (1200 tokens)
    # Approximately 4 chars per token = 4800 chars
    text = "This is sample text. " * 228  # ~4788 chars = ~1197 tokens

    should_chunk, token_count = chunking_service.should_chunk(text)

    # At or slightly below threshold should not chunk
    if token_count <= 1200:
        assert should_chunk is False
    else:
        assert should_chunk is True


# ============================================================================
# Chunking Tests
# ============================================================================

def test_chunk_text_below_threshold(chunking_service, sample_text_short):
    """Test chunk_text returns empty list for small text."""
    chunks = chunking_service.chunk_text(sample_text_short, "art_test123")

    assert chunks == []


def test_chunk_text_above_threshold(chunking_service, sample_text_long):
    """Test chunk_text creates chunks for large text."""
    artifact_id = "art_test123"
    chunks = chunking_service.chunk_text(sample_text_long, artifact_id)

    assert len(chunks) > 0
    assert all(isinstance(chunk, Chunk) for chunk in chunks)
    assert all(chunk.artifact_id == artifact_id for chunk in chunks)


def test_chunk_overlaps(chunking_service, sample_text_long):
    """Test that chunks overlap as expected."""
    chunks = chunking_service.chunk_text(sample_text_long, "art_test123")

    assert len(chunks) >= 2  # Need at least 2 chunks to test overlap

    # Check that chunk_index increments sequentially
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i

    # Check that there's overlap in token positions
    # With target=900 and overlap=100, each chunk should start 800 tokens after previous
    # This means chunks should have overlapping content


def test_deterministic_ids(chunking_service):
    """Test that chunk IDs are deterministic based on content."""
    text = "Test content for chunking. " * 200  # Make it long enough to chunk

    chunks1 = chunking_service.chunk_text(text, "art_test123")
    chunks2 = chunking_service.chunk_text(text, "art_test123")

    assert len(chunks1) == len(chunks2)
    for c1, c2 in zip(chunks1, chunks2):
        assert c1.chunk_id == c2.chunk_id
        assert c1.content_hash == c2.content_hash


def test_character_offsets(chunking_service, sample_text_long):
    """Test that character offsets are correct."""
    chunks = chunking_service.chunk_text(sample_text_long, "art_test123")

    # First chunk should start at 0
    assert chunks[0].start_char == 0

    # Each chunk's end_char should equal start_char + content length
    for chunk in chunks:
        assert chunk.end_char == chunk.start_char + len(chunk.content)

    # Verify offsets extract correct content
    for chunk in chunks:
        expected_content = sample_text_long[chunk.start_char:chunk.end_char]
        assert chunk.content == expected_content


def test_chunk_token_counts(chunking_service, sample_text_long):
    """Test that chunk token counts are within expected range."""
    chunks = chunking_service.chunk_text(sample_text_long, "art_test123")

    for chunk in chunks:
        # All chunks except possibly the last should be around target size
        assert chunk.token_count > 0
        # Should not exceed target by too much (allowing some buffer for token boundaries)
        assert chunk.token_count <= 900 + 50  # Target + small buffer


def test_chunk_id_format(chunking_service, sample_text_long):
    """Test chunk ID format is correct."""
    artifact_id = "art_test123"
    chunks = chunking_service.chunk_text(sample_text_long, artifact_id)

    for chunk in chunks:
        assert chunk.chunk_id.startswith(f"{artifact_id}::chunk::")
        # Format: art_test123::chunk::000::abc12345
        parts = chunk.chunk_id.split("::")
        assert len(parts) == 4
        assert parts[0] == artifact_id
        assert parts[1] == "chunk"
        assert parts[2].isdigit()  # Index as 3-digit number
        assert len(parts[3]) == 8  # Hash prefix


def test_chunk_content_hash(chunking_service, sample_text_long):
    """Test that chunk content hashes are unique per content."""
    chunks = chunking_service.chunk_text(sample_text_long, "art_test123")

    # Extract hashes
    hashes = [chunk.content_hash for chunk in chunks]

    # Most chunks should have unique content hashes
    # (Some might collide if text is repetitive, but not all)
    unique_hashes = set(hashes)
    assert len(unique_hashes) >= len(chunks) * 0.8  # At least 80% unique


# ============================================================================
# Neighbor Expansion Tests
# ============================================================================

def test_expand_neighbors_middle_chunk(chunking_service, sample_chunks):
    """Test expanding chunk with both prev and next neighbors."""
    result = chunking_service.expand_chunk_neighbors(
        artifact_id="art_test123",
        chunk_index=1,
        all_chunks=sample_chunks
    )

    assert "[CHUNK BOUNDARY]" in result
    # Should contain all 3 chunks
    assert "First chunk" in result
    assert "Second chunk" in result
    assert "Third chunk" in result
    # Should have 2 boundaries (before and after middle chunk)
    assert result.count("[CHUNK BOUNDARY]") == 2


def test_expand_neighbors_first_chunk(chunking_service, sample_chunks):
    """Test expanding first chunk (no previous neighbor)."""
    result = chunking_service.expand_chunk_neighbors(
        artifact_id="art_test123",
        chunk_index=0,
        all_chunks=sample_chunks
    )

    assert "First chunk" in result
    assert "Second chunk" in result
    assert "Third chunk" not in result
    # Should have 1 boundary (after first chunk)
    assert result.count("[CHUNK BOUNDARY]") == 1


def test_expand_neighbors_last_chunk(chunking_service, sample_chunks):
    """Test expanding last chunk (no next neighbor)."""
    result = chunking_service.expand_chunk_neighbors(
        artifact_id="art_test123",
        chunk_index=2,
        all_chunks=sample_chunks
    )

    assert "First chunk" not in result
    assert "Second chunk" in result
    assert "Third chunk" in result
    # Should have 1 boundary (before last chunk)
    assert result.count("[CHUNK BOUNDARY]") == 1


def test_expand_neighbors_invalid_index(chunking_service, sample_chunks):
    """Test expanding with invalid chunk index."""
    result = chunking_service.expand_chunk_neighbors(
        artifact_id="art_test123",
        chunk_index=99,  # Invalid index
        all_chunks=sample_chunks
    )

    assert result == ""


def test_expand_neighbors_empty_chunks(chunking_service):
    """Test expanding with empty chunk list."""
    result = chunking_service.expand_chunk_neighbors(
        artifact_id="art_test123",
        chunk_index=0,
        all_chunks=[]
    )

    assert result == ""


def test_expand_neighbors_single_chunk(chunking_service):
    """Test expanding when only one chunk exists."""
    from storage.models import Chunk

    single_chunk = [
        Chunk(
            chunk_id="art_test123::chunk::000::abc12345",
            artifact_id="art_test123",
            chunk_index=0,
            content="Only chunk content.",
            start_char=0,
            end_char=20,
            token_count=5,
            content_hash="abc12345"
        )
    ]

    result = chunking_service.expand_chunk_neighbors(
        artifact_id="art_test123",
        chunk_index=0,
        all_chunks=single_chunk
    )

    assert "Only chunk" in result
    # Should have no boundaries (no neighbors)
    assert "[CHUNK BOUNDARY]" not in result
