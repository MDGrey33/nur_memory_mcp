"""Configuration management for MCP Memory Server v2.0."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # OpenAI Configuration
    openai_api_key: str
    openai_embed_model: str
    openai_embed_dims: int
    openai_timeout: int
    openai_max_retries: int
    openai_batch_size: int

    # V3: OpenAI Event Extraction Model
    openai_event_model: str

    # Chunking Configuration
    single_piece_max_tokens: int
    chunk_target_tokens: int
    chunk_overlap_tokens: int

    # ChromaDB Configuration
    chroma_host: str
    chroma_port: int

    # V3: Postgres Configuration
    events_db_dsn: str
    postgres_pool_min: int
    postgres_pool_max: int

    # V3: Worker Configuration
    worker_id: Optional[str]
    poll_interval_ms: int
    event_max_attempts: int

    # Server Configuration
    mcp_port: int
    log_level: str

    # RRF Configuration
    rrf_constant: int


def load_config() -> Config:
    """
    Load configuration from environment variables.

    Returns:
        Config object with all settings

    Raises:
        ValueError: If required environment variables are missing
    """
    # Required variables
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError(
            "OPENAI_API_KEY environment variable is required. "
            "Please set it in your .env file or environment."
        )

    return Config(
        # OpenAI
        openai_api_key=openai_api_key,
        openai_embed_model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-large"),
        openai_embed_dims=int(os.getenv("OPENAI_EMBED_DIMS", "3072")),
        openai_timeout=int(os.getenv("OPENAI_TIMEOUT", "30")),
        openai_max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "3")),
        openai_batch_size=int(os.getenv("OPENAI_BATCH_SIZE", "100")),

        # V3: OpenAI Event Extraction
        openai_event_model=os.getenv("OPENAI_EVENT_MODEL", "gpt-4o-mini"),

        # Chunking
        single_piece_max_tokens=int(os.getenv("SINGLE_PIECE_MAX_TOKENS", "1200")),
        chunk_target_tokens=int(os.getenv("CHUNK_TARGET_TOKENS", "900")),
        chunk_overlap_tokens=int(os.getenv("CHUNK_OVERLAP_TOKENS", "100")),

        # ChromaDB
        chroma_host=os.getenv("CHROMA_HOST", "localhost"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8001")),

        # V3: Postgres
        events_db_dsn=os.getenv("EVENTS_DB_DSN", "postgresql://events:events@localhost:5432/events"),
        postgres_pool_min=int(os.getenv("POSTGRES_POOL_MIN", "2")),
        postgres_pool_max=int(os.getenv("POSTGRES_POOL_MAX", "10")),

        # V3: Worker
        worker_id=os.getenv("WORKER_ID"),  # Optional, only for worker processes
        poll_interval_ms=int(os.getenv("POLL_INTERVAL_MS", "1000")),
        event_max_attempts=int(os.getenv("EVENT_MAX_ATTEMPTS", "5")),

        # Server
        mcp_port=int(os.getenv("MCP_PORT", "3000")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),

        # RRF
        rrf_constant=int(os.getenv("RRF_CONSTANT", "60")),
    )


def validate_config(config: Config) -> None:
    """
    Validate configuration values.

    Args:
        config: Configuration to validate

    Raises:
        ValueError: If any configuration value is invalid
    """
    # Validate OpenAI dimensions
    if config.openai_embed_dims not in [256, 1024, 3072]:
        raise ValueError(
            f"Invalid OPENAI_EMBED_DIMS: {config.openai_embed_dims}. "
            "Must be one of: 256, 1024, 3072"
        )

    # Validate chunking parameters
    if config.chunk_target_tokens >= config.single_piece_max_tokens:
        raise ValueError(
            f"CHUNK_TARGET_TOKENS ({config.chunk_target_tokens}) must be less than "
            f"SINGLE_PIECE_MAX_TOKENS ({config.single_piece_max_tokens})"
        )

    if config.chunk_overlap_tokens >= config.chunk_target_tokens:
        raise ValueError(
            f"CHUNK_OVERLAP_TOKENS ({config.chunk_overlap_tokens}) must be less than "
            f"CHUNK_TARGET_TOKENS ({config.chunk_target_tokens})"
        )

    # Validate batch size
    if config.openai_batch_size > 2048:
        raise ValueError(
            f"OPENAI_BATCH_SIZE ({config.openai_batch_size}) exceeds OpenAI limit of 2048"
        )

    # Validate log level
    valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if config.log_level.upper() not in valid_log_levels:
        raise ValueError(
            f"Invalid LOG_LEVEL: {config.log_level}. "
            f"Must be one of: {', '.join(valid_log_levels)}"
        )
