"""OpenAI embedding generation service with retry logic."""

import logging
import time
from typing import List

import openai
from openai import OpenAI

from utils.errors import ConfigurationError, EmbeddingError, ValidationError


logger = logging.getLogger("mcp-memory.embedding")


class EmbeddingService:
    """Centralized OpenAI embedding generation service with retry logic."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-large",
        dimensions: int = 3072,
        timeout: int = 30,
        max_retries: int = 3,
        batch_size: int = 100
    ):
        """
        Initialize embedding service.

        Args:
            api_key: OpenAI API key
            model: Embedding model name
            dimensions: Embedding dimensions
            timeout: Request timeout (seconds)
            max_retries: Max retry attempts for transient failures
            batch_size: Max texts per batch (≤2048 per OpenAI limit)
        """
        if not api_key:
            raise ConfigurationError("OpenAI API key is required")

        self.client = OpenAI(api_key=api_key, timeout=timeout)
        self.model = model
        self.dimensions = dimensions
        self.max_retries = max_retries
        self.batch_size = min(batch_size, 2048)  # OpenAI limit
        self.timeout = timeout

    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate single embedding with retry logic.

        Args:
            text: Text to embed (should be ≤8191 tokens)

        Returns:
            Embedding vector (dimensions as configured)

        Raises:
            ValidationError: Invalid input (empty, too long)
            ConfigurationError: Invalid API key
            EmbeddingError: Generation failed after retries
        """
        if not text or not text.strip():
            raise ValidationError("Text cannot be empty")

        try:
            start_time = time.time()

            response = self._call_with_retry(
                self.client.embeddings.create,
                input=[text],
                model=self.model,
                dimensions=self.dimensions
            )

            embedding = response.data[0].embedding
            latency_ms = int((time.time() - start_time) * 1000)

            logger.info(
                f"Generated embedding: model={self.model}, "
                f"dims={self.dimensions}, latency={latency_ms}ms"
            )

            return embedding

        except (ValidationError, ConfigurationError):
            raise
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise EmbeddingError(f"Failed to generate embedding: {e}")

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts efficiently.

        Automatically splits into batches if texts > batch_size.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors (same order as input)

        Raises:
            ValidationError: Invalid input
            EmbeddingError: Generation failed after retries
        """
        if not texts:
            return []

        # Validate inputs
        for i, text in enumerate(texts):
            if not text or not text.strip():
                raise ValidationError(f"Text at index {i} is empty")

        all_embeddings = []

        # Split into batches
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (len(texts) + self.batch_size - 1) // self.batch_size

            try:
                start_time = time.time()

                response = self._call_with_retry(
                    self.client.embeddings.create,
                    input=batch,
                    model=self.model,
                    dimensions=self.dimensions
                )

                # Extract embeddings in order
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)

                latency_ms = int((time.time() - start_time) * 1000)

                logger.info(
                    f"Batch {batch_num}/{total_batches}: "
                    f"generated {len(batch)} embeddings in {latency_ms}ms"
                )

            except Exception as e:
                logger.error(
                    f"Batch {batch_num}/{total_batches} failed: {e}"
                )
                raise EmbeddingError(
                    f"Failed to generate embeddings for batch {batch_num}: {e}"
                )

        return all_embeddings

    def _call_with_retry(self, func, *args, **kwargs):
        """
        Execute function with exponential backoff retry logic.

        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            ConfigurationError: For auth errors (no retry)
            ValidationError: For invalid input (no retry)
            EmbeddingError: After max retries exceeded
        """
        attempts = 0
        backoff = 1.0  # seconds

        while attempts < self.max_retries:
            try:
                return func(*args, **kwargs)

            except openai.AuthenticationError as e:
                # Don't retry auth errors
                raise ConfigurationError(
                    "Invalid OpenAI API key. Check OPENAI_API_KEY environment variable."
                ) from e

            except openai.BadRequestError as e:
                # Don't retry invalid input
                raise ValidationError(f"Invalid input: {e}") from e

            except openai.RateLimitError as e:
                attempts += 1
                if attempts >= self.max_retries:
                    raise EmbeddingError(
                        f"OpenAI rate limit reached after {attempts} attempts. "
                        "Try again later."
                    ) from e

                logger.warning(
                    f"Rate limit hit (attempt {attempts}/{self.max_retries}), "
                    f"retrying in {backoff}s"
                )
                time.sleep(backoff)
                backoff *= 2

            except (openai.APITimeoutError, openai.APIConnectionError) as e:
                attempts += 1
                if attempts >= self.max_retries:
                    raise EmbeddingError(
                        f"Request timeout after {attempts} attempts"
                    ) from e

                logger.warning(
                    f"Timeout (attempt {attempts}/{self.max_retries}), "
                    f"retrying in {backoff}s"
                )
                time.sleep(backoff)
                backoff *= 2

            except (openai.InternalServerError, openai.APIError) as e:
                attempts += 1
                if attempts >= self.max_retries:
                    raise EmbeddingError(
                        f"OpenAI service error after {attempts} attempts"
                    ) from e

                logger.warning(
                    f"OpenAI service error (attempt {attempts}/{self.max_retries}), "
                    f"retrying in {backoff}s"
                )
                time.sleep(backoff)
                backoff *= 2

        raise EmbeddingError(f"Failed after {self.max_retries} attempts")

    def get_model_info(self) -> dict:
        """
        Return model configuration.

        Returns:
            Dictionary with provider, model, dimensions, batch_size
        """
        return {
            "provider": "openai",
            "model": self.model,
            "dimensions": self.dimensions,
            "batch_size": self.batch_size,
            "timeout": self.timeout,
            "max_retries": self.max_retries
        }

    def health_check(self) -> dict:
        """
        Test API connectivity with small embedding.

        Returns:
            Dictionary with status, latency_ms, and optional error
        """
        try:
            start_time = time.time()
            self.generate_embedding("test")
            latency_ms = int((time.time() - start_time) * 1000)

            return {
                "status": "healthy",
                "model": self.model,
                "dimensions": self.dimensions,
                "api_latency_ms": latency_ms
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "model": self.model,
                "error": str(e)
            }
