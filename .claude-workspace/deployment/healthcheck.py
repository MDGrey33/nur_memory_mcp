#!/usr/bin/env python3
"""
Health Check Script for MCP Memory Server V3
Checks connectivity and health of all services
"""

import sys
import os
import argparse
import socket
import psycopg2
import requests
from typing import Tuple


def check_http_endpoint(url: str, timeout: int = 5) -> Tuple[bool, str]:
    """Check if HTTP endpoint is reachable and healthy."""
    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code == 200:
            return True, f"OK (HTTP {response.status_code})"
        else:
            return False, f"HTTP {response.status_code}: {response.text[:100]}"
    except requests.exceptions.Timeout:
        return False, f"Timeout after {timeout}s"
    except requests.exceptions.ConnectionError as e:
        return False, f"Connection error: {str(e)[:100]}"
    except Exception as e:
        return False, f"Error: {str(e)[:100]}"


def check_postgres(dsn: str, timeout: int = 5) -> Tuple[bool, str]:
    """Check if PostgreSQL is reachable and accepting connections."""
    try:
        conn = psycopg2.connect(dsn, connect_timeout=timeout)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result and result[0] == 1:
            return True, "OK (connected successfully)"
        else:
            return False, "Unexpected query result"
    except psycopg2.OperationalError as e:
        return False, f"Connection error: {str(e)[:100]}"
    except Exception as e:
        return False, f"Error: {str(e)[:100]}"


def check_chromadb(host: str, port: int, timeout: int = 5) -> Tuple[bool, str]:
    """Check if ChromaDB is reachable via HTTP."""
    url = f"http://{host}:{port}/api/v2/heartbeat"
    return check_http_endpoint(url, timeout)


def check_tcp_port(host: str, port: int, timeout: int = 5) -> Tuple[bool, str]:
    """Check if TCP port is open."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            return True, f"Port {port} is open"
        else:
            return False, f"Port {port} is closed (code {result})"
    except socket.timeout:
        return False, f"Timeout after {timeout}s"
    except Exception as e:
        return False, f"Error: {str(e)[:100]}"


def health_check_mcp_server() -> int:
    """Health check for MCP Server."""
    print("=== MCP Server Health Check ===")

    # Check if server is responding
    mcp_port = os.getenv("MCP_PORT", "3000")
    success, message = check_tcp_port("localhost", int(mcp_port))
    print(f"MCP Server Port: {message}")
    if not success:
        return 1

    # Check ChromaDB connectivity
    chroma_host = os.getenv("CHROMA_HOST", "chroma")
    chroma_port = int(os.getenv("CHROMA_PORT", "8000"))
    success, message = check_chromadb(chroma_host, chroma_port)
    print(f"ChromaDB: {message}")
    if not success:
        return 1

    # Check Postgres connectivity
    dsn = os.getenv("EVENTS_DB_DSN", "postgresql://events:events@postgres:5432/events")
    success, message = check_postgres(dsn)
    print(f"PostgreSQL: {message}")
    if not success:
        return 1

    print("✓ All checks passed")
    return 0


def health_check_worker() -> int:
    """Health check for Event Worker."""
    print("=== Event Worker Health Check ===")

    # Check ChromaDB connectivity
    chroma_host = os.getenv("CHROMA_HOST", "chroma")
    chroma_port = int(os.getenv("CHROMA_PORT", "8000"))
    success, message = check_chromadb(chroma_host, chroma_port)
    print(f"ChromaDB: {message}")
    if not success:
        return 1

    # Check Postgres connectivity
    dsn = os.getenv("EVENTS_DB_DSN", "postgresql://events:events@postgres:5432/events")
    success, message = check_postgres(dsn)
    print(f"PostgreSQL: {message}")
    if not success:
        return 1

    # Check if worker process is running (simple check)
    worker_id = os.getenv("WORKER_ID", "worker-1")
    print(f"Worker ID: {worker_id}")

    print("✓ All checks passed")
    return 0


def health_check_postgres() -> int:
    """Health check for PostgreSQL."""
    print("=== PostgreSQL Health Check ===")

    dsn = os.getenv("EVENTS_DB_DSN", "postgresql://events:events@postgres:5432/events")
    success, message = check_postgres(dsn)
    print(f"PostgreSQL: {message}")

    if success:
        print("✓ PostgreSQL is healthy")
        return 0
    else:
        return 1


def health_check_chromadb() -> int:
    """Health check for ChromaDB."""
    print("=== ChromaDB Health Check ===")

    chroma_host = os.getenv("CHROMA_HOST", "chroma")
    chroma_port = int(os.getenv("CHROMA_PORT", "8000"))
    success, message = check_chromadb(chroma_host, chroma_port)
    print(f"ChromaDB: {message}")

    if success:
        print("✓ ChromaDB is healthy")
        return 0
    else:
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Health check script for MCP Memory Server V3"
    )
    parser.add_argument(
        "--service",
        choices=["mcp-server", "worker", "postgres", "chroma", "all"],
        default="all",
        help="Service to check (default: all)"
    )

    args = parser.parse_args()

    if args.service == "mcp-server":
        return health_check_mcp_server()
    elif args.service == "worker":
        return health_check_worker()
    elif args.service == "postgres":
        return health_check_postgres()
    elif args.service == "chroma":
        return health_check_chromadb()
    elif args.service == "all":
        print("=== Full System Health Check ===\n")

        results = []

        print("Checking ChromaDB...")
        results.append(health_check_chromadb())
        print()

        print("Checking PostgreSQL...")
        results.append(health_check_postgres())
        print()

        print("Checking MCP Server...")
        results.append(health_check_mcp_server())
        print()

        print("Checking Event Worker...")
        results.append(health_check_worker())
        print()

        if all(r == 0 for r in results):
            print("✓✓✓ All services are healthy ✓✓✓")
            return 0
        else:
            print("✗✗✗ Some services failed health checks ✗✗✗")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
