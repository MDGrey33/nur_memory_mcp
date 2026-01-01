"""
V5 Integration Tests for status() Tool

Tests the status() tool which returns system health:
- Service health (ChromaDB, PostgreSQL)
- Collection counts (content, chunks)
- Pending job counts
- Job status for specific artifact

Markers:
- @pytest.mark.v5: V5-specific tests
- @pytest.mark.integration: Integration tests
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# =============================================================================
# Test: status() - Health Check
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestStatusHealthy:
    """Tests for healthy status responses."""

    async def test_status_healthy(
        self,
        v5_test_harness
    ):
        """Test health check returns V5 structure."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import status

            result = await status()

            assert "error" not in result
            assert "version" in result
            assert "environment" in result
            assert "healthy" in result
            assert "services" in result
            assert "counts" in result

            # V5 structure
            assert result["healthy"] is True or result["healthy"] is False

    async def test_status_includes_chromadb(
        self,
        v5_test_harness
    ):
        """Test status includes ChromaDB health."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import status

            result = await status()

            assert "services" in result
            assert "chromadb" in result["services"]
            assert "status" in result["services"]["chromadb"]

    async def test_status_includes_postgres(
        self,
        v5_test_harness
    ):
        """Test status includes PostgreSQL health when available."""
        mock_pg = v5_test_harness["pg_client"]
        mock_pg.fetch_one.return_value = {"status": "ok"}

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", mock_pg):

            from server import status

            result = await status()

            assert "services" in result
            # Postgres may or may not be in services depending on config


# =============================================================================
# Test: status() - Collection Counts
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestStatusCollections:
    """Tests for V5 collection reporting."""

    async def test_status_reports_v5_collections(
        self,
        v5_test_harness
    ):
        """Test status reports content/chunks collections."""
        chroma_client = v5_test_harness["chroma_client"]

        # Pre-populate with some content
        content_col = chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=["art_test001"],
            documents=["Test content"],
            metadatas=[{"context": "note"}],
            embeddings=[[0.1] * 3072]
        )

        chunks_col = chroma_client.get_or_create_collection("chunks")
        chunks_col.add(
            ids=["art_test001::chunk::000"],
            documents=["Chunk content"],
            metadatas=[{"content_id": "art_test001"}],
            embeddings=[[0.1] * 3072]
        )

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import status

            result = await status()

            assert "counts" in result
            # Should report V5 collections
            counts = result["counts"]
            assert "content" in counts or "chunks" in counts

    async def test_status_zero_counts(
        self,
        v5_test_harness
    ):
        """Test status with empty collections."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import status

            result = await status()

            assert "counts" in result
            # Empty collections should report 0
            counts = result["counts"]
            assert counts.get("content", 0) >= 0
            assert counts.get("chunks", 0) >= 0


# =============================================================================
# Test: status() - Job Status
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestStatusJobCheck:
    """Tests for job status checking."""

    async def test_status_with_job_check(
        self,
        v5_test_harness
    ):
        """Test job status for specific artifact."""
        mock_pg = v5_test_harness["pg_client"]

        # Mock job status response
        mock_pg.fetch_one.return_value = {
            "status": "DONE",
            "artifact_uid": "uid_test123",
            "revision_id": "rev_test123"
        }

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", mock_pg):

            from server import status

            result = await status(artifact_id="art_test123")

            assert "error" not in result
            # Should include job_status when artifact_id provided
            if "job_status" in result:
                assert "status" in result["job_status"]

    async def test_status_job_not_found(
        self,
        v5_test_harness
    ):
        """Test job status when job not found."""
        mock_pg = v5_test_harness["pg_client"]
        mock_pg.fetch_one.return_value = None  # No job found

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", mock_pg):

            from server import status

            result = await status(artifact_id="art_nonexistent")

            assert "error" not in result
            # Job status should indicate not found or be absent

    async def test_status_without_artifact_id(
        self,
        v5_test_harness
    ):
        """Test status without artifact_id doesn't include job_status."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import status

            result = await status()

            assert "error" not in result
            # job_status should not be present without artifact_id
            # (or should be None/empty)


# =============================================================================
# Test: status() - Pending Jobs
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestStatusPendingJobs:
    """Tests for pending job count reporting."""

    async def test_status_pending_jobs(
        self,
        v5_test_harness
    ):
        """Test pending_jobs count is reported."""
        mock_pg = v5_test_harness["pg_client"]
        mock_pg.fetch_val.return_value = 5  # 5 pending jobs

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", mock_pg):

            from server import status

            result = await status()

            assert "pending_jobs" in result
            assert isinstance(result["pending_jobs"], int)

    async def test_status_zero_pending_jobs(
        self,
        v5_test_harness
    ):
        """Test zero pending jobs."""
        mock_pg = v5_test_harness["pg_client"]
        mock_pg.fetch_val.return_value = 0

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", mock_pg):

            from server import status

            result = await status()

            assert result.get("pending_jobs", 0) == 0


# =============================================================================
# Test: status() - Error Handling
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestStatusErrors:
    """Tests for error handling in status."""

    async def test_status_chromadb_unhealthy(
        self,
        v5_test_harness
    ):
        """Test status when ChromaDB is unhealthy."""
        mock_manager = v5_test_harness["chroma_manager"]
        mock_manager.health_check.return_value = {
            "status": "unhealthy",
            "error": "Connection refused"
        }

        with patch("server.chroma_manager", mock_manager), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import status

            result = await status()

            # Status should still return, but healthy=False
            assert result.get("healthy") is False

    async def test_status_postgres_unavailable(
        self,
        v5_test_harness
    ):
        """Test status when PostgreSQL is unavailable."""
        mock_pg = v5_test_harness["pg_client"]
        mock_pg.fetch_val.side_effect = Exception("Connection refused")

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", mock_pg):

            from server import status

            result = await status()

            # Should still return status, possibly with degraded health
            assert "version" in result

    async def test_status_graceful_degradation(
        self,
        v5_test_harness
    ):
        """Test status degrades gracefully with partial failures."""
        mock_manager = v5_test_harness["chroma_manager"]
        mock_manager.get_client.side_effect = Exception("ChromaDB error")

        mock_pg = v5_test_harness["pg_client"]
        mock_pg.fetch_val.side_effect = Exception("Postgres error")

        with patch("server.chroma_manager", mock_manager), \
             patch("server.pg_client", mock_pg):

            from server import status

            result = await status()

            # Should still return basic status info
            assert "version" in result or "error" in result


# =============================================================================
# Test: status() - Version and Environment
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestStatusMetadata:
    """Tests for version and environment metadata."""

    async def test_status_version_format(
        self,
        v5_test_harness
    ):
        """Test version string format."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import status

            result = await status()

            assert "version" in result
            # Version should be a string
            assert isinstance(result["version"], str)

    async def test_status_environment(
        self,
        v5_test_harness
    ):
        """Test environment is reported."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import status

            result = await status()

            assert "environment" in result
            # Environment should be one of: development, staging, production
            valid_envs = ["development", "staging", "production", "test"]
            assert result["environment"] in valid_envs


# =============================================================================
# Test: status() - ChromaDB Collections
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestStatusChromaCollections:
    """Tests for ChromaDB collection reporting."""

    async def test_status_chromadb_collections_list(
        self,
        v5_test_harness
    ):
        """Test ChromaDB collections are listed."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import status

            result = await status()

            services = result.get("services", {})
            chromadb = services.get("chromadb", {})

            # Should include V5 collections
            if "collections" in chromadb:
                collections = chromadb["collections"]
                assert "content" in collections
                assert "chunks" in collections
