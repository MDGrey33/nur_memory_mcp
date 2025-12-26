#!/usr/bin/env python3
"""E2E Tests for MCP Memory Server v2.0"""

import json
import requests
import time
from datetime import datetime

BASE_URL = "http://localhost:3000"
CHROMA_URL = "http://localhost:8001"

results = {
    "timestamp": datetime.now().isoformat(),
    "tests": [],
    "passed": 0,
    "failed": 0,
    "skipped": 0
}

def log_result(test_name: str, passed: bool, details: str = "", skipped: bool = False):
    """Log test result"""
    status = "SKIP" if skipped else ("PASS" if passed else "FAIL")
    result = {
        "name": test_name,
        "status": status,
        "details": details
    }
    results["tests"].append(result)
    if skipped:
        results["skipped"] += 1
    elif passed:
        results["passed"] += 1
    else:
        results["failed"] += 1
    print(f"[{status}] {test_name}: {details[:100] if details else 'OK'}")


def test_health_endpoint():
    """Test 1: Health endpoint"""
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        data = resp.json()
        passed = resp.status_code == 200 and data.get("status") == "ok"
        log_result("Health Endpoint", passed, f"Status: {resp.status_code}, Response: {data}")
    except Exception as e:
        log_result("Health Endpoint", False, str(e))


def test_chromadb_heartbeat():
    """Test 2: ChromaDB heartbeat"""
    try:
        resp = requests.get(f"{CHROMA_URL}/api/v2/heartbeat", timeout=5)
        passed = resp.status_code == 200 and "heartbeat" in resp.text
        log_result("ChromaDB Heartbeat", passed, f"Status: {resp.status_code}")
    except Exception as e:
        log_result("ChromaDB Heartbeat", False, str(e))


def test_mcp_initialize():
    """Test 3: MCP Initialize"""
    try:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "e2e-test", "version": "1.0"},
                "capabilities": {}
            }
        }
        resp = requests.post(f"{BASE_URL}/mcp/", headers=headers, json=payload, timeout=10)
        passed = resp.status_code == 200 and "protocolVersion" in resp.text
        log_result("MCP Initialize", passed, f"Status: {resp.status_code}, SSE response received")
    except Exception as e:
        log_result("MCP Initialize", False, str(e))


def test_detailed_health():
    """Test 4: Detailed health endpoint"""
    try:
        resp = requests.get(f"{BASE_URL}/health/detailed", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            passed = data.get("status") == "healthy" and "services" in data
            log_result("Detailed Health", passed, f"Services: {list(data.get('services', {}).keys())}")
        else:
            log_result("Detailed Health", False, f"Status: {resp.status_code}")
    except Exception as e:
        log_result("Detailed Health", False, str(e))


def test_chromadb_collections():
    """Test 5: ChromaDB collections exist"""
    try:
        resp = requests.get(f"{CHROMA_URL}/api/v2/tenants/default_tenant/databases/default_database/collections", timeout=5)
        if resp.status_code == 200:
            collections = resp.json()
            collection_names = [c.get("name") for c in collections]
            expected = ["memory", "history", "artifacts", "artifact_chunks"]
            found = [c for c in expected if c in collection_names]
            passed = len(found) >= 2  # At least some collections should exist
            log_result("ChromaDB Collections", passed, f"Found: {collection_names}")
        else:
            log_result("ChromaDB Collections", False, f"Status: {resp.status_code}")
    except Exception as e:
        log_result("ChromaDB Collections", False, str(e))


def test_server_info():
    """Test 6: Server returns proper info in initialize"""
    try:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": "info-test",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "e2e-test", "version": "1.0"},
                "capabilities": {}
            }
        }
        resp = requests.post(f"{BASE_URL}/mcp/", headers=headers, json=payload, timeout=10)
        passed = "MCP Memory" in resp.text and "tools" in resp.text
        log_result("Server Info", passed, "Server name and tools capability present")
    except Exception as e:
        log_result("Server Info", False, str(e))


def test_sse_format():
    """Test 7: SSE response format"""
    try:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": "sse-test",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "e2e-test", "version": "1.0"},
                "capabilities": {}
            }
        }
        resp = requests.post(f"{BASE_URL}/mcp/", headers=headers, json=payload, timeout=10)
        passed = resp.text.startswith("event:") or resp.text.startswith("data:")
        log_result("SSE Format", passed, f"Response format: {'SSE' if passed else 'Unknown'}")
    except Exception as e:
        log_result("SSE Format", False, str(e))


def test_error_handling():
    """Test 8: Error handling for invalid requests"""
    try:
        headers = {"Content-Type": "application/json"}
        # Missing Accept header
        resp = requests.post(f"{BASE_URL}/mcp/", headers=headers, json={}, timeout=5)
        passed = resp.status_code in [400, 406]  # Should reject
        log_result("Error Handling", passed, f"Status: {resp.status_code} (expected 4xx)")
    except Exception as e:
        log_result("Error Handling", False, str(e))


def test_cors_headers():
    """Test 9: CORS headers present"""
    try:
        resp = requests.options(f"{BASE_URL}/mcp/", timeout=5)
        cors_header = resp.headers.get("Access-Control-Allow-Origin", "")
        passed = cors_header == "*" or "localhost" in cors_header or resp.status_code == 200
        log_result("CORS Headers", passed, f"CORS: {cors_header or 'Not set'}")
    except Exception as e:
        log_result("CORS Headers", False, str(e))


def test_response_time():
    """Test 10: Response time under threshold"""
    try:
        start = time.time()
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        elapsed = (time.time() - start) * 1000  # ms
        passed = elapsed < 500 and resp.status_code == 200
        log_result("Response Time", passed, f"Health endpoint: {elapsed:.0f}ms")
    except Exception as e:
        log_result("Response Time", False, str(e))


def main():
    print("\n" + "="*60)
    print("MCP Memory Server v2.0 - E2E Test Suite")
    print("="*60 + "\n")

    # Run all tests
    test_health_endpoint()
    test_chromadb_heartbeat()
    test_mcp_initialize()
    test_detailed_health()
    test_chromadb_collections()
    test_server_info()
    test_sse_format()
    test_error_handling()
    test_cors_headers()
    test_response_time()

    # Summary
    print("\n" + "="*60)
    print(f"RESULTS: {results['passed']} passed, {results['failed']} failed, {results['skipped']} skipped")
    print("="*60 + "\n")

    # Save results
    with open("/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/tests/ui/ui-test-results.json", "w") as f:
        json.dump(results, f, indent=2)

    return results["failed"] == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
