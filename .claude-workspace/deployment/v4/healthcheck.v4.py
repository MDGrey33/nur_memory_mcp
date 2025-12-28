#!/usr/bin/env python3
"""
MCP Memory V4 Health Check Script

Performs comprehensive health checks for V4 services including:
- ChromaDB connectivity
- PostgreSQL connectivity
- Apache AGE graph health
- Entity resolution service
- MCP server endpoints

Usage:
    python healthcheck.v4.py --service all
    python healthcheck.v4.py --service mcp-server --v4
    python healthcheck.v4.py --service graph
    python healthcheck.v4.py --service entity-resolution

Exit codes:
    0 = All checks passed
    1 = One or more checks failed
"""

import argparse
import asyncio
import json
import os
import sys
from typing import Dict, Any, Optional
from urllib.parse import urlparse

# Optional: use httpx if available, fallback to urllib
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_HTTPX = False

# Optional: use asyncpg if available
try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False


class HealthChecker:
    """Health checker for MCP Memory V4 services."""

    def __init__(self, v4_mode: bool = True):
        self.v4_mode = v4_mode
        self.results: Dict[str, Dict[str, Any]] = {}

        # Configuration from environment
        self.chroma_host = os.getenv("CHROMA_HOST", "chroma")
        self.chroma_port = os.getenv("CHROMA_PORT", "8000")
        self.mcp_port = os.getenv("MCP_PORT", "3000")
        self.db_dsn = os.getenv("EVENTS_DB_DSN", "")
        self.graph_enabled = os.getenv("V4_GRAPH_ENABLED", "true").lower() == "true"
        self.graph_name = os.getenv("V4_GRAPH_NAME", "nur")

    def _http_get(self, url: str, timeout: float = 5.0) -> tuple[int, str]:
        """Make HTTP GET request, returns (status_code, body)."""
        if HAS_HTTPX:
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.get(url)
                    return response.status_code, response.text
            except Exception as e:
                return 0, str(e)
        else:
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return response.status, response.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, str(e)
            except Exception as e:
                return 0, str(e)

    def check_chroma(self) -> Dict[str, Any]:
        """Check ChromaDB health."""
        url = f"http://{self.chroma_host}:{self.chroma_port}/api/v2/heartbeat"
        status_code, body = self._http_get(url)

        result = {
            "service": "chroma",
            "url": url,
            "status": "healthy" if status_code == 200 else "unhealthy",
            "status_code": status_code,
        }

        if status_code != 200:
            result["error"] = body

        self.results["chroma"] = result
        return result

    def check_mcp_server(self) -> Dict[str, Any]:
        """Check MCP server health."""
        url = f"http://localhost:{self.mcp_port}/health"
        status_code, body = self._http_get(url)

        result = {
            "service": "mcp-server",
            "url": url,
            "status": "healthy" if status_code == 200 else "unhealthy",
            "status_code": status_code,
        }

        if status_code == 200:
            try:
                data = json.loads(body)
                result["version"] = data.get("version", "unknown")
                result["details"] = data
            except json.JSONDecodeError:
                result["response"] = body
        else:
            result["error"] = body

        self.results["mcp-server"] = result
        return result

    def check_graph(self) -> Dict[str, Any]:
        """Check graph health (V4 only)."""
        if not self.v4_mode:
            return {"service": "graph", "status": "skipped", "reason": "V4 mode disabled"}

        if not self.graph_enabled:
            return {"service": "graph", "status": "skipped", "reason": "Graph disabled"}

        url = f"http://localhost:{self.mcp_port}/health/graph"
        status_code, body = self._http_get(url)

        result = {
            "service": "graph",
            "url": url,
            "status": "unknown",
            "status_code": status_code,
        }

        if status_code == 200:
            try:
                data = json.loads(body)
                result["age_enabled"] = data.get("age_enabled", False)
                result["graph_exists"] = data.get("graph_exists", False)
                result["entity_count"] = data.get("entity_node_count", 0)
                result["event_count"] = data.get("event_node_count", 0)

                if data.get("age_enabled") and data.get("graph_exists"):
                    result["status"] = "healthy"
                else:
                    result["status"] = "unhealthy"
                    result["error"] = "AGE or graph not available"

            except json.JSONDecodeError:
                result["status"] = "unhealthy"
                result["error"] = "Invalid JSON response"
        else:
            result["status"] = "unhealthy"
            result["error"] = body

        self.results["graph"] = result
        return result

    def check_entity_resolution(self) -> Dict[str, Any]:
        """Check entity resolution service health (V4 only)."""
        if not self.v4_mode:
            return {"service": "entity-resolution", "status": "skipped", "reason": "V4 mode disabled"}

        url = f"http://localhost:{self.mcp_port}/health/entity-resolution"
        status_code, body = self._http_get(url)

        result = {
            "service": "entity-resolution",
            "url": url,
            "status": "unknown",
            "status_code": status_code,
        }

        if status_code == 200:
            try:
                data = json.loads(body)
                result["embedding_service"] = data.get("embedding_service", "unknown")
                result["pg_connection"] = data.get("pg_connection", "unknown")
                result["entity_count"] = data.get("entity_count", 0)
                result["pending_review"] = data.get("pending_review_count", 0)

                # All subsystems must be OK
                if (data.get("embedding_service") == "ok" and
                    data.get("pg_connection") == "ok"):
                    result["status"] = "healthy"
                else:
                    result["status"] = "degraded"
                    result["error"] = "One or more subsystems unhealthy"

            except json.JSONDecodeError:
                result["status"] = "unhealthy"
                result["error"] = "Invalid JSON response"
        elif status_code == 404:
            # Endpoint may not exist yet
            result["status"] = "not_implemented"
            result["error"] = "Endpoint not available"
        else:
            result["status"] = "unhealthy"
            result["error"] = body

        self.results["entity-resolution"] = result
        return result

    async def check_postgres_async(self) -> Dict[str, Any]:
        """Check PostgreSQL connectivity (async)."""
        if not HAS_ASYNCPG:
            return {"service": "postgres", "status": "skipped", "reason": "asyncpg not installed"}

        if not self.db_dsn:
            return {"service": "postgres", "status": "unhealthy", "error": "EVENTS_DB_DSN not set"}

        result = {
            "service": "postgres",
            "status": "unknown",
        }

        try:
            conn = await asyncpg.connect(self.db_dsn, timeout=5)

            # Basic connectivity
            version = await conn.fetchval("SELECT version()")
            result["version"] = version.split()[1] if version else "unknown"

            # Check V4 tables exist
            if self.v4_mode:
                v4_tables = await conn.fetchval("""
                    SELECT COUNT(*) FROM pg_tables
                    WHERE tablename IN ('entity', 'entity_alias', 'entity_mention', 'event_actor', 'event_subject')
                """)
                result["v4_tables"] = v4_tables

                # Check AGE if enabled
                if self.graph_enabled:
                    age_exists = await conn.fetchval("""
                        SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'age')
                    """)
                    result["age_extension"] = age_exists

                    if age_exists:
                        graph_exists = await conn.fetchval("""
                            SELECT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = $1)
                        """, self.graph_name)
                        result["graph_exists"] = graph_exists

            await conn.close()
            result["status"] = "healthy"

        except asyncpg.InvalidCatalogNameError as e:
            result["status"] = "unhealthy"
            result["error"] = f"Database not found: {e}"
        except asyncpg.InvalidPasswordError as e:
            result["status"] = "unhealthy"
            result["error"] = "Invalid password"
        except Exception as e:
            result["status"] = "unhealthy"
            result["error"] = str(e)

        self.results["postgres"] = result
        return result

    def check_postgres(self) -> Dict[str, Any]:
        """Check PostgreSQL connectivity (sync wrapper)."""
        if HAS_ASYNCPG:
            return asyncio.run(self.check_postgres_async())
        else:
            return {"service": "postgres", "status": "skipped", "reason": "asyncpg not installed"}

    def check_worker(self) -> Dict[str, Any]:
        """Check event worker status by examining recent job activity."""
        if not self.db_dsn or not HAS_ASYNCPG:
            return {"service": "worker", "status": "skipped", "reason": "Cannot check without DB"}

        async def _check():
            try:
                conn = await asyncpg.connect(self.db_dsn, timeout=5)

                # Check for stuck jobs
                stuck_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM event_jobs
                    WHERE status = 'PROCESSING'
                    AND locked_at < now() - interval '5 minutes'
                """)

                # Check pending job count
                pending_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM event_jobs WHERE status = 'PENDING'
                """)

                # Check recent completions
                recent_done = await conn.fetchval("""
                    SELECT COUNT(*) FROM event_jobs
                    WHERE status = 'DONE'
                    AND updated_at > now() - interval '10 minutes'
                """)

                await conn.close()

                status = "healthy"
                issues = []

                if stuck_count > 0:
                    status = "degraded"
                    issues.append(f"{stuck_count} stuck jobs")

                if pending_count > 100:
                    status = "degraded"
                    issues.append(f"{pending_count} pending jobs (queue backlog)")

                return {
                    "service": "worker",
                    "status": status,
                    "stuck_jobs": stuck_count,
                    "pending_jobs": pending_count,
                    "recent_completions": recent_done,
                    "issues": issues if issues else None
                }

            except Exception as e:
                return {"service": "worker", "status": "unhealthy", "error": str(e)}

        result = asyncio.run(_check())
        self.results["worker"] = result
        return result

    def check_all(self) -> Dict[str, Dict[str, Any]]:
        """Run all health checks."""
        self.check_chroma()
        self.check_postgres()
        self.check_mcp_server()

        if self.v4_mode:
            self.check_graph()
            self.check_entity_resolution()

        self.check_worker()

        return self.results

    def get_overall_status(self) -> str:
        """Get overall status from all results."""
        if not self.results:
            return "unknown"

        statuses = [r.get("status", "unknown") for r in self.results.values()]

        if all(s in ["healthy", "skipped", "not_implemented"] for s in statuses):
            return "healthy"
        elif any(s == "unhealthy" for s in statuses):
            return "unhealthy"
        else:
            return "degraded"


def main():
    parser = argparse.ArgumentParser(description="MCP Memory V4 Health Check")
    parser.add_argument(
        "--service",
        choices=["all", "chroma", "postgres", "mcp-server", "graph", "entity-resolution", "worker"],
        default="all",
        help="Service to check"
    )
    parser.add_argument(
        "--v4",
        action="store_true",
        default=True,
        help="Enable V4 checks (default: true)"
    )
    parser.add_argument(
        "--no-v4",
        action="store_true",
        help="Disable V4-specific checks"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only output on failure"
    )

    args = parser.parse_args()

    v4_mode = not args.no_v4
    checker = HealthChecker(v4_mode=v4_mode)

    # Run checks
    if args.service == "all":
        results = checker.check_all()
    elif args.service == "chroma":
        results = {"chroma": checker.check_chroma()}
    elif args.service == "postgres":
        results = {"postgres": checker.check_postgres()}
    elif args.service == "mcp-server":
        results = {"mcp-server": checker.check_mcp_server()}
    elif args.service == "graph":
        results = {"graph": checker.check_graph()}
    elif args.service == "entity-resolution":
        results = {"entity-resolution": checker.check_entity_resolution()}
    elif args.service == "worker":
        results = {"worker": checker.check_worker()}

    overall = checker.get_overall_status()

    # Output
    if args.json:
        output = {
            "overall_status": overall,
            "v4_mode": v4_mode,
            "checks": results
        }
        print(json.dumps(output, indent=2))
    elif not args.quiet or overall != "healthy":
        print(f"\nMCP Memory Health Check (V4={v4_mode})")
        print("=" * 50)

        for service, result in results.items():
            status = result.get("status", "unknown")
            status_symbol = {
                "healthy": "[OK]",
                "unhealthy": "[FAIL]",
                "degraded": "[WARN]",
                "skipped": "[SKIP]",
                "not_implemented": "[N/A]",
            }.get(status, "[???]")

            print(f"{status_symbol} {service}: {status}")

            if result.get("error"):
                print(f"     Error: {result['error']}")

            if result.get("issues"):
                for issue in result["issues"]:
                    print(f"     - {issue}")

        print("=" * 50)
        print(f"Overall: {overall.upper()}")

    # Exit code
    sys.exit(0 if overall == "healthy" else 1)


if __name__ == "__main__":
    main()
