"""
Postgres client with connection pooling for V3 event storage.

Uses asyncpg for async operations and psycopg2 for sync fallback.
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any, Tuple
from contextlib import asynccontextmanager
import asyncpg
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

logger = logging.getLogger("postgres_client")


class PostgresClient:
    """Async Postgres client with connection pooling."""

    def __init__(
        self,
        dsn: str,
        min_pool_size: int = 2,
        max_pool_size: int = 10,
        command_timeout: float = 60.0
    ):
        """
        Initialize Postgres client.

        Args:
            dsn: PostgreSQL connection string (e.g., postgresql://user:pass@host:port/db)
            min_pool_size: Minimum pool connections
            max_pool_size: Maximum pool connections
            command_timeout: Query timeout in seconds
        """
        self.dsn = dsn
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self.command_timeout = command_timeout
        self._pool: Optional[asyncpg.Pool] = None
        self._sync_pool: Optional[SimpleConnectionPool] = None

    async def connect(self) -> None:
        """Create async connection pool."""
        if self._pool is not None:
            logger.warning("Pool already exists, skipping connect")
            return

        try:
            self._pool = await asyncpg.create_pool(
                self.dsn,
                min_size=self.min_pool_size,
                max_size=self.max_pool_size,
                command_timeout=self.command_timeout
            )
            logger.info(f"Postgres async pool created: {self.min_pool_size}-{self.max_pool_size} connections")
        except Exception as e:
            logger.error(f"Failed to create async pool: {e}")
            raise

    async def close(self) -> None:
        """Close async connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Postgres async pool closed")

    def connect_sync(self) -> None:
        """Create sync connection pool (psycopg2 fallback)."""
        if self._sync_pool is not None:
            logger.warning("Sync pool already exists, skipping connect")
            return

        try:
            self._sync_pool = SimpleConnectionPool(
                self.min_pool_size,
                self.max_pool_size,
                self.dsn
            )
            logger.info(f"Postgres sync pool created: {self.min_pool_size}-{self.max_pool_size} connections")
        except Exception as e:
            logger.error(f"Failed to create sync pool: {e}")
            raise

    def close_sync(self) -> None:
        """Close sync connection pool."""
        if self._sync_pool:
            self._sync_pool.closeall()
            self._sync_pool = None
            logger.info("Postgres sync pool closed")

    @asynccontextmanager
    async def acquire(self):
        """Acquire async connection from pool."""
        if not self._pool:
            raise RuntimeError("Pool not initialized. Call connect() first.")

        async with self._pool.acquire() as connection:
            yield connection

    async def execute(
        self,
        query: str,
        *args,
        timeout: Optional[float] = None
    ) -> str:
        """
        Execute a query (INSERT/UPDATE/DELETE) and return status.

        Args:
            query: SQL query with $1, $2, ... placeholders
            *args: Query parameters
            timeout: Optional query timeout

        Returns:
            Status string (e.g., "INSERT 0 1")
        """
        async with self.acquire() as conn:
            return await conn.execute(query, *args, timeout=timeout or self.command_timeout)

    async def fetch_all(
        self,
        query: str,
        *args,
        timeout: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch all rows as list of dicts.

        Args:
            query: SQL query with $1, $2, ... placeholders
            *args: Query parameters
            timeout: Optional query timeout

        Returns:
            List of row dicts
        """
        async with self.acquire() as conn:
            rows = await conn.fetch(query, *args, timeout=timeout or self.command_timeout)
            return [dict(row) for row in rows]

    async def fetch_one(
        self,
        query: str,
        *args,
        timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch one row as dict.

        Args:
            query: SQL query with $1, $2, ... placeholders
            *args: Query parameters
            timeout: Optional query timeout

        Returns:
            Row dict or None
        """
        async with self.acquire() as conn:
            row = await conn.fetchrow(query, *args, timeout=timeout or self.command_timeout)
            return dict(row) if row else None

    async def fetch_val(
        self,
        query: str,
        *args,
        timeout: Optional[float] = None
    ) -> Any:
        """
        Fetch single value.

        Args:
            query: SQL query with $1, $2, ... placeholders
            *args: Query parameters
            timeout: Optional query timeout

        Returns:
            Single value or None
        """
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args, timeout=timeout or self.command_timeout)

    async def transaction(self, queries: List[Tuple[str, tuple]]) -> None:
        """
        Execute multiple queries in a transaction.

        Args:
            queries: List of (query, args) tuples

        Raises:
            Exception: If any query fails (transaction rolled back)
        """
        async with self.acquire() as conn:
            async with conn.transaction():
                for query, args in queries:
                    await conn.execute(query, *args)

    def execute_sync(self, query: str, params: Optional[tuple] = None) -> Any:
        """
        Execute a query synchronously (fallback for worker).

        Args:
            query: SQL query with %s placeholders
            params: Query parameters tuple

        Returns:
            Cursor result
        """
        if not self._sync_pool:
            raise RuntimeError("Sync pool not initialized. Call connect_sync() first.")

        conn = self._sync_pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params or ())
                conn.commit()

                # Try to fetch results if SELECT
                try:
                    return cursor.fetchall()
                except psycopg2.ProgrammingError:
                    # No results to fetch (INSERT/UPDATE/DELETE)
                    return cursor.rowcount
        except Exception as e:
            conn.rollback()
            raise
        finally:
            self._sync_pool.putconn(conn)

    def fetch_all_sync(self, query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """
        Fetch all rows synchronously.

        Args:
            query: SQL query with %s placeholders
            params: Query parameters tuple

        Returns:
            List of row dicts
        """
        if not self._sync_pool:
            raise RuntimeError("Sync pool not initialized. Call connect_sync() first.")

        conn = self._sync_pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params or ())
                return cursor.fetchall()
        finally:
            self._sync_pool.putconn(conn)

    def fetch_one_sync(self, query: str, params: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
        """
        Fetch one row synchronously.

        Args:
            query: SQL query with %s placeholders
            params: Query parameters tuple

        Returns:
            Row dict or None
        """
        if not self._sync_pool:
            raise RuntimeError("Sync pool not initialized. Call connect_sync() first.")

        conn = self._sync_pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params or ())
                return cursor.fetchone()
        finally:
            self._sync_pool.putconn(conn)

    async def health_check(self) -> Dict[str, Any]:
        """
        Check database health.

        Returns:
            Health status dict
        """
        try:
            if not self._pool:
                return {
                    "status": "unhealthy",
                    "error": "Pool not initialized"
                }

            # Simple query to test connection
            result = await self.fetch_val("SELECT 1")

            if result == 1:
                return {
                    "status": "healthy",
                    "pool_size": self._pool.get_size(),
                    "pool_free": self._pool.get_size() - self._pool.get_idle_size(),
                    "pool_max": self.max_pool_size
                }
            else:
                return {
                    "status": "unhealthy",
                    "error": "Unexpected query result"
                }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }

    def health_check_sync(self) -> Dict[str, Any]:
        """
        Check database health synchronously.

        Returns:
            Health status dict
        """
        try:
            if not self._sync_pool:
                return {
                    "status": "unhealthy",
                    "error": "Sync pool not initialized"
                }

            # Simple query to test connection
            result = self.fetch_one_sync("SELECT 1 AS test")

            if result and result.get("test") == 1:
                return {
                    "status": "healthy",
                    "pool_info": "psycopg2 connection pool active"
                }
            else:
                return {
                    "status": "unhealthy",
                    "error": "Unexpected query result"
                }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
