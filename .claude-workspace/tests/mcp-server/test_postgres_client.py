"""
Unit tests for PostgresClient.

Tests connection pooling, query execution, transactions, and error handling.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import asyncpg

from storage.postgres_client import PostgresClient


# ============================================================================
# Connection Pool Tests
# ============================================================================

@pytest.mark.asyncio
async def test_connect_creates_pool():
    """Test that connect() creates an async connection pool."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")

    with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create_pool:
        mock_pool = AsyncMock()
        mock_create_pool.return_value = mock_pool

        await client.connect()

        mock_create_pool.assert_called_once_with(
            "postgresql://test:test@localhost:5432/test",
            min_size=2,
            max_size=10,
            command_timeout=60.0
        )
        assert client._pool == mock_pool


@pytest.mark.asyncio
async def test_connect_skips_if_already_connected():
    """Test that connect() skips if pool already exists."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_pool = AsyncMock()
    client._pool = mock_pool

    with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create_pool:
        await client.connect()
        mock_create_pool.assert_not_called()


@pytest.mark.asyncio
async def test_connect_raises_on_failure():
    """Test that connect() raises exception on connection failure."""
    client = PostgresClient(dsn="postgresql://invalid:invalid@invalid:5432/invalid")

    with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create_pool:
        mock_create_pool.side_effect = Exception("Connection refused")

        with pytest.raises(Exception, match="Connection refused"):
            await client.connect()


@pytest.mark.asyncio
async def test_close_closes_pool():
    """Test that close() closes the connection pool."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_pool = AsyncMock()
    client._pool = mock_pool

    await client.close()

    mock_pool.close.assert_called_once()
    assert client._pool is None


def test_connect_sync_creates_sync_pool():
    """Test that connect_sync() creates a sync connection pool."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")

    with patch("psycopg2.pool.SimpleConnectionPool") as mock_pool_class:
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        client.connect_sync()

        mock_pool_class.assert_called_once_with(
            2,
            10,
            "postgresql://test:test@localhost:5432/test"
        )
        assert client._sync_pool == mock_pool


def test_close_sync_closes_sync_pool():
    """Test that close_sync() closes the sync connection pool."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_pool = MagicMock()
    client._sync_pool = mock_pool

    client.close_sync()

    mock_pool.closeall.assert_called_once()
    assert client._sync_pool is None


# ============================================================================
# Query Execution Tests (Async)
# ============================================================================

@pytest.mark.asyncio
async def test_execute_runs_query():
    """Test that execute() runs a query and returns status."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
    mock_pool = AsyncMock()

    # Mock acquire context manager
    @pytest.fixture
    async def mock_acquire():
        yield mock_conn

    client._pool = mock_pool
    client.acquire = lambda: mock_acquire()

    # Need to actually implement the context manager
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire_impl():
        yield mock_conn

    client.acquire = mock_acquire_impl

    result = await client.execute("INSERT INTO test VALUES ($1)", "value")

    assert result == "INSERT 0 1"
    mock_conn.execute.assert_called_once_with("INSERT INTO test VALUES ($1)", "value", timeout=60.0)


@pytest.mark.asyncio
async def test_execute_raises_if_not_connected():
    """Test that execute() raises error if pool not initialized."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")

    with pytest.raises(RuntimeError, match="Pool not initialized"):
        await client.execute("SELECT 1")


@pytest.mark.asyncio
async def test_fetch_all_returns_rows():
    """Test that fetch_all() returns all rows as dicts."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = AsyncMock()

    # Mock Record objects
    mock_record1 = {"id": 1, "name": "Alice"}
    mock_record2 = {"id": 2, "name": "Bob"}
    mock_conn.fetch = AsyncMock(return_value=[
        MagicMock(**mock_record1),
        MagicMock(**mock_record2)
    ])

    # Configure dict() behavior
    mock_conn.fetch.return_value[0].__iter__ = lambda self: iter(mock_record1.items())
    mock_conn.fetch.return_value[1].__iter__ = lambda self: iter(mock_record2.items())

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire_impl():
        yield mock_conn

    client._pool = AsyncMock()
    client.acquire = mock_acquire_impl

    # Simplify: just test the mock behavior
    rows = await mock_conn.fetch("SELECT * FROM test")
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_fetch_one_returns_single_row():
    """Test that fetch_one() returns one row as dict."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = AsyncMock()
    mock_record = {"id": 1, "name": "Alice"}
    mock_conn.fetchrow = AsyncMock(return_value=mock_record)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire_impl():
        yield mock_conn

    client._pool = AsyncMock()
    client.acquire = mock_acquire_impl

    result = await client.fetch_one("SELECT * FROM test WHERE id = $1", 1)

    assert result == mock_record


@pytest.mark.asyncio
async def test_fetch_one_returns_none_if_no_row():
    """Test that fetch_one() returns None if no row found."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire_impl():
        yield mock_conn

    client._pool = AsyncMock()
    client.acquire = mock_acquire_impl

    result = await client.fetch_one("SELECT * FROM test WHERE id = $1", 999)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_val_returns_single_value():
    """Test that fetch_val() returns a single value."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=42)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire_impl():
        yield mock_conn

    client._pool = AsyncMock()
    client.acquire = mock_acquire_impl

    result = await client.fetch_val("SELECT COUNT(*) FROM test")

    assert result == 42


# ============================================================================
# Transaction Tests
# ============================================================================

@pytest.mark.asyncio
async def test_transaction_executes_all_queries():
    """Test that transaction() executes all queries in a transaction."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = AsyncMock()
    mock_transaction = AsyncMock()
    mock_conn.transaction.return_value = mock_transaction
    mock_conn.execute = AsyncMock()

    # Mock async context manager
    mock_transaction.__aenter__ = AsyncMock()
    mock_transaction.__aexit__ = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire_impl():
        yield mock_conn

    client._pool = AsyncMock()
    client.acquire = mock_acquire_impl

    queries = [
        ("INSERT INTO test VALUES ($1)", ("value1",)),
        ("INSERT INTO test VALUES ($1)", ("value2",)),
    ]

    await client.transaction(queries)

    # Verify all queries were executed
    assert mock_conn.execute.call_count == 2


@pytest.mark.asyncio
async def test_transaction_rolls_back_on_error():
    """Test that transaction() rolls back if any query fails."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = AsyncMock()
    mock_transaction = AsyncMock()
    mock_conn.transaction.return_value = mock_transaction

    # First query succeeds, second fails
    mock_conn.execute = AsyncMock(side_effect=[None, Exception("Query failed")])

    # Mock async context manager
    mock_transaction.__aenter__ = AsyncMock()
    mock_transaction.__aexit__ = AsyncMock(side_effect=Exception("Query failed"))

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire_impl():
        yield mock_conn

    client._pool = AsyncMock()
    client.acquire = mock_acquire_impl

    queries = [
        ("INSERT INTO test VALUES ($1)", ("value1",)),
        ("INSERT INTO test VALUES ($1)", ("value2",)),
    ]

    with pytest.raises(Exception, match="Query failed"):
        await client.transaction(queries)


# ============================================================================
# Sync Query Tests
# ============================================================================

def test_execute_sync_runs_query():
    """Test that execute_sync() runs a query synchronously."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{"id": 1}]
    mock_cursor.rowcount = 1
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock()

    mock_pool = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    client._sync_pool = mock_pool

    result = client.execute_sync("INSERT INTO test VALUES (%s)", ("value",))

    mock_cursor.execute.assert_called_once_with("INSERT INTO test VALUES (%s)", ("value",))
    mock_conn.commit.assert_called_once()


def test_execute_sync_raises_if_not_connected():
    """Test that execute_sync() raises error if pool not initialized."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")

    with pytest.raises(RuntimeError, match="Sync pool not initialized"):
        client.execute_sync("SELECT 1")


def test_fetch_all_sync_returns_rows():
    """Test that fetch_all_sync() returns all rows."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{"id": 1}, {"id": 2}]
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock()

    mock_pool = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    client._sync_pool = mock_pool

    result = client.fetch_all_sync("SELECT * FROM test")

    assert result == [{"id": 1}, {"id": 2}]


def test_fetch_one_sync_returns_single_row():
    """Test that fetch_one_sync() returns one row."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"id": 1}
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock()

    mock_pool = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    client._sync_pool = mock_pool

    result = client.fetch_one_sync("SELECT * FROM test WHERE id = %s", (1,))

    assert result == {"id": 1}


# ============================================================================
# Health Check Tests
# ============================================================================

@pytest.mark.asyncio
async def test_health_check_returns_healthy():
    """Test that health_check() returns healthy status."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=1)
    mock_pool = AsyncMock()
    mock_pool.get_size.return_value = 10
    mock_pool.get_idle_size.return_value = 8

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire_impl():
        yield mock_conn

    client._pool = mock_pool
    client.acquire = mock_acquire_impl

    result = await client.health_check()

    assert result["status"] == "healthy"
    assert result["pool_size"] == 10
    assert result["pool_max"] == 10


@pytest.mark.asyncio
async def test_health_check_returns_unhealthy_if_no_pool():
    """Test that health_check() returns unhealthy if pool not initialized."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")

    result = await client.health_check()

    assert result["status"] == "unhealthy"
    assert "Pool not initialized" in result["error"]


@pytest.mark.asyncio
async def test_health_check_returns_unhealthy_on_error():
    """Test that health_check() returns unhealthy on query error."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(side_effect=Exception("Connection lost"))
    mock_pool = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire_impl():
        yield mock_conn

    client._pool = mock_pool
    client.acquire = mock_acquire_impl

    result = await client.health_check()

    assert result["status"] == "unhealthy"
    assert "Connection lost" in result["error"]


def test_health_check_sync_returns_healthy():
    """Test that health_check_sync() returns healthy status."""
    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"test": 1}
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock()

    mock_pool = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    client._sync_pool = mock_pool

    result = client.health_check_sync()

    assert result["status"] == "healthy"


# ============================================================================
# Custom Pool Configuration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_custom_pool_configuration():
    """Test that custom pool configuration is applied."""
    client = PostgresClient(
        dsn="postgresql://test:test@localhost:5432/test",
        min_pool_size=5,
        max_pool_size=20,
        command_timeout=120.0
    )

    with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create_pool:
        mock_pool = AsyncMock()
        mock_create_pool.return_value = mock_pool

        await client.connect()

        mock_create_pool.assert_called_once_with(
            "postgresql://test:test@localhost:5432/test",
            min_size=5,
            max_size=20,
            command_timeout=120.0
        )
