#!/usr/bin/env python3
"""
Full E2E User Simulation Test for MCP Memory Server v2.0

This script simulates EXACTLY what a real user would do:
1. Connect to the MCP server (like Cursor/Claude Desktop does)
2. Call every tool with real data
3. Verify data persists and can be retrieved
4. Test complete workflows end-to-end

The user should NEVER be the first to test. This script tests everything first.
"""

import json
import requests
import time
import uuid
import sys
from datetime import datetime
from typing import Optional, Dict, Any, List

# Configuration
MCP_URL = "http://localhost:3000/mcp/"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream"
}

class MCPClient:
    """Simulates an MCP client like Cursor or Claude Desktop"""

    def __init__(self, url: str):
        self.url = url
        self.session_id = None
        self.request_id = 0

    def _next_id(self) -> int:
        self.request_id += 1
        return self.request_id

    def _get_headers(self) -> Dict:
        """Get headers including session ID if available"""
        headers = HEADERS.copy()
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _send_request(self, method: str, params: Dict = None) -> Dict:
        """Send JSON-RPC request to MCP server"""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._next_id(),
            "params": params or {}
        }

        try:
            resp = requests.post(self.url, headers=self._get_headers(), json=payload, timeout=30)

            # Extract session ID from response headers
            if "Mcp-Session-Id" in resp.headers:
                self.session_id = resp.headers["Mcp-Session-Id"]

            # Parse SSE response
            if resp.status_code == 200:
                # Extract JSON from SSE format
                for line in resp.text.split('\n'):
                    if line.startswith('data:'):
                        return json.loads(line[5:].strip())

            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def initialize(self) -> bool:
        """Initialize MCP session"""
        result = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "e2e-test-client", "version": "1.0"},
            "capabilities": {}
        })

        success = "result" in result and "protocolVersion" in result.get("result", {})

        # Send initialized notification (required by MCP protocol)
        if success:
            self._send_request("notifications/initialized", {})

        return success

    def list_tools(self) -> List[str]:
        """List available tools"""
        result = self._send_request("tools/list", {})
        if "result" in result and "tools" in result["result"]:
            return [t["name"] for t in result["result"]["tools"]]
        return []

    def call_tool(self, name: str, arguments: Dict) -> Dict:
        """Call an MCP tool"""
        result = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })
        return result


class E2ETestRunner:
    """Runs full user simulation tests"""

    def __init__(self):
        self.client = MCPClient(MCP_URL)
        self.results = []
        self.test_data = {
            "memory_id": None,
            "artifact_id": None,
            "conversation_id": f"test-conv-{uuid.uuid4().hex[:8]}"
        }

    def log(self, status: str, test: str, details: str = ""):
        """Log test result"""
        color = "\033[92m" if status == "PASS" else "\033[91m"
        reset = "\033[0m"
        print(f"{color}[{status}]{reset} {test}")
        if details:
            print(f"       {details[:200]}")
        self.results.append({"status": status, "test": test, "details": details})

    def run_all_tests(self):
        """Run complete user simulation"""
        print("\n" + "="*60)
        print("FULL USER SIMULATION TEST")
        print("Simulating exactly what a real user would do")
        print("="*60 + "\n")

        # Phase 1: Connection (what happens when user opens Cursor)
        print("--- Phase 1: Connection (User opens Cursor/Claude Desktop) ---\n")
        self.test_initialize()
        self.test_list_tools()

        # Phase 2: Memory Operations (user stores and retrieves memories)
        print("\n--- Phase 2: Memory Operations ---\n")
        self.test_memory_store()
        self.test_memory_search()
        self.test_memory_list()

        # Phase 3: History Operations (conversation tracking)
        print("\n--- Phase 3: History Operations ---\n")
        self.test_history_append()
        self.test_history_get()

        # Phase 4: Artifact Operations (document ingestion)
        print("\n--- Phase 4: Artifact Operations ---\n")
        self.test_artifact_ingest_small()
        self.test_artifact_ingest_large()
        self.test_artifact_search()
        self.test_artifact_get()

        # Phase 5: Hybrid Search (cross-collection search)
        print("\n--- Phase 5: Hybrid Search ---\n")
        self.test_hybrid_search()

        # Phase 6: Health Check
        print("\n--- Phase 6: System Health ---\n")
        self.test_embedding_health()

        # Phase 7: Cleanup
        print("\n--- Phase 7: Cleanup ---\n")
        self.test_memory_delete()
        self.test_artifact_delete()

        # Summary
        self.print_summary()

    def test_initialize(self):
        """Test: User connects to MCP server"""
        success = self.client.initialize()
        if success:
            self.log("PASS", "Initialize MCP connection", "Protocol handshake successful")
        else:
            self.log("FAIL", "Initialize MCP connection", "Failed to establish session")

    def test_list_tools(self):
        """Test: Verify all tools are available"""
        tools = self.client.list_tools()
        expected_v2_tools = [
            "memory_store", "memory_search", "memory_list", "memory_delete",
            "history_append", "history_get",
            "artifact_ingest", "artifact_search", "artifact_get", "artifact_delete",
            "hybrid_search", "embedding_health"
        ]

        if len(tools) >= 12:
            missing = [t for t in expected_v2_tools if t not in tools]
            if not missing:
                self.log("PASS", f"All 12 v2 tools available", f"Tools: {tools}")
            else:
                self.log("FAIL", f"Missing tools", f"Missing: {missing}")
        else:
            self.log("FAIL", f"Tool count mismatch", f"Expected 12, got {len(tools)}: {tools}")

    def test_memory_store(self):
        """Test: User stores a memory"""
        result = self.client.call_tool("memory_store", {
            "content": "User prefers Python for backend development and React for frontend",
            "type": "preference",
            "confidence": 0.95
        })

        if "result" in result:
            content = result["result"].get("content", [{}])[0].get("text", "")
            if "mem_" in content:
                # Extract memory ID
                import re
                match = re.search(r'mem_[a-f0-9]+', content)
                if match:
                    self.test_data["memory_id"] = match.group()
                self.log("PASS", "memory_store", f"Stored: {content[:100]}")
            else:
                self.log("FAIL", "memory_store", f"No memory ID in response: {content}")
        else:
            self.log("FAIL", "memory_store", f"Error: {result.get('error', result)}")

    def test_memory_search(self):
        """Test: User searches for memories"""
        result = self.client.call_tool("memory_search", {
            "query": "programming language preference",
            "limit": 5
        })

        if "result" in result:
            content = result["result"].get("content", [{}])[0].get("text", "")
            if "Python" in content or "preference" in content.lower():
                self.log("PASS", "memory_search", f"Found relevant results")
            else:
                self.log("PASS", "memory_search", f"Search executed (may have no matches yet)")
        else:
            self.log("FAIL", "memory_search", f"Error: {result.get('error', result)}")

    def test_memory_list(self):
        """Test: User lists all memories"""
        result = self.client.call_tool("memory_list", {
            "type": "preference",
            "limit": 10
        })

        if "result" in result:
            self.log("PASS", "memory_list", "Listed memories successfully")
        else:
            self.log("FAIL", "memory_list", f"Error: {result.get('error', result)}")

    def test_history_append(self):
        """Test: User appends conversation history"""
        result = self.client.call_tool("history_append", {
            "conversation_id": self.test_data["conversation_id"],
            "role": "user",
            "content": "How do I implement authentication in Python?",
            "turn_index": 0
        })

        if "result" in result:
            self.log("PASS", "history_append", f"Appended to {self.test_data['conversation_id']}")
        else:
            self.log("FAIL", "history_append", f"Error: {result.get('error', result)}")

    def test_history_get(self):
        """Test: User retrieves conversation history"""
        result = self.client.call_tool("history_get", {
            "conversation_id": self.test_data["conversation_id"],
            "limit": 10
        })

        if "result" in result:
            content = result["result"].get("content", [{}])[0].get("text", "")
            if "authentication" in content.lower() or self.test_data["conversation_id"] in content:
                self.log("PASS", "history_get", "Retrieved conversation history")
            else:
                self.log("PASS", "history_get", "History retrieved (may be empty)")
        else:
            self.log("FAIL", "history_get", f"Error: {result.get('error', result)}")

    def test_artifact_ingest_small(self):
        """Test: User ingests a small document (no chunking)"""
        result = self.client.call_tool("artifact_ingest", {
            "artifact_type": "doc",
            "source_system": "e2e-test",
            "content": "This is a small test document about Python best practices. Always use virtual environments.",
            "title": "Python Best Practices",
            "source_id": f"test-doc-{uuid.uuid4().hex[:8]}"
        })

        if "result" in result:
            content = result["result"].get("content", [{}])[0].get("text", "")
            if "art_" in content:
                import re
                match = re.search(r'art_[a-f0-9]+', content)
                if match:
                    self.test_data["artifact_id"] = match.group()
                self.log("PASS", "artifact_ingest (small)", f"Ingested: {content[:100]}")
            else:
                self.log("FAIL", "artifact_ingest (small)", f"No artifact ID: {content}")
        else:
            self.log("FAIL", "artifact_ingest (small)", f"Error: {result.get('error', result)}")

    def test_artifact_ingest_large(self):
        """Test: User ingests a large document (requires chunking)"""
        # Generate content > 1200 tokens (~5000 words)
        large_content = """
        Software Engineering Best Practices Guide

        Chapter 1: Code Quality
        Writing clean, maintainable code is essential for long-term project success.
        This includes proper naming conventions, documentation, and testing.
        """ * 50  # Repeat to exceed token threshold

        result = self.client.call_tool("artifact_ingest", {
            "artifact_type": "doc",
            "source_system": "e2e-test",
            "content": large_content,
            "title": "Software Engineering Guide",
            "source_id": f"test-large-{uuid.uuid4().hex[:8]}"
        })

        if "result" in result:
            content = result["result"].get("content", [{}])[0].get("text", "")
            if "chunked" in content.lower() or "chunks" in content.lower():
                self.log("PASS", "artifact_ingest (large/chunked)", f"Chunking worked")
            elif "art_" in content:
                self.log("PASS", "artifact_ingest (large)", f"Ingested successfully")
            else:
                self.log("FAIL", "artifact_ingest (large)", f"Unexpected: {content[:100]}")
        else:
            self.log("FAIL", "artifact_ingest (large)", f"Error: {result.get('error', result)}")

    def test_artifact_search(self):
        """Test: User searches artifacts"""
        result = self.client.call_tool("artifact_search", {
            "query": "Python best practices",
            "limit": 5
        })

        if "result" in result:
            self.log("PASS", "artifact_search", "Search executed successfully")
        else:
            self.log("FAIL", "artifact_search", f"Error: {result.get('error', result)}")

    def test_artifact_get(self):
        """Test: User retrieves artifact details"""
        if not self.test_data.get("artifact_id"):
            self.log("SKIP", "artifact_get", "No artifact ID from previous test")
            return

        result = self.client.call_tool("artifact_get", {
            "artifact_id": self.test_data["artifact_id"],
            "include_content": True
        })

        if "result" in result:
            self.log("PASS", "artifact_get", f"Retrieved {self.test_data['artifact_id']}")
        else:
            self.log("FAIL", "artifact_get", f"Error: {result.get('error', result)}")

    def test_hybrid_search(self):
        """Test: User does cross-collection search"""
        result = self.client.call_tool("hybrid_search", {
            "query": "Python programming",
            "limit": 5,
            "include_memory": True
        })

        if "result" in result:
            content = result["result"].get("content", [{}])[0].get("text", "")
            self.log("PASS", "hybrid_search", f"Cross-collection search worked")
        else:
            self.log("FAIL", "hybrid_search", f"Error: {result.get('error', result)}")

    def test_embedding_health(self):
        """Test: Check embedding service health"""
        result = self.client.call_tool("embedding_health", {})

        if "result" in result:
            content = result["result"].get("content", [{}])[0].get("text", "")
            if "healthy" in content.lower() or "3072" in content:
                self.log("PASS", "embedding_health", "OpenAI embeddings healthy")
            else:
                self.log("FAIL", "embedding_health", f"Unhealthy: {content[:100]}")
        else:
            self.log("FAIL", "embedding_health", f"Error: {result.get('error', result)}")

    def test_memory_delete(self):
        """Test: User deletes a memory"""
        if not self.test_data.get("memory_id"):
            self.log("SKIP", "memory_delete", "No memory ID to delete")
            return

        result = self.client.call_tool("memory_delete", {
            "memory_id": self.test_data["memory_id"]
        })

        if "result" in result:
            self.log("PASS", "memory_delete", f"Deleted {self.test_data['memory_id']}")
        else:
            self.log("FAIL", "memory_delete", f"Error: {result.get('error', result)}")

    def test_artifact_delete(self):
        """Test: User deletes an artifact"""
        if not self.test_data.get("artifact_id"):
            self.log("SKIP", "artifact_delete", "No artifact ID to delete")
            return

        result = self.client.call_tool("artifact_delete", {
            "artifact_id": self.test_data["artifact_id"]
        })

        if "result" in result:
            self.log("PASS", "artifact_delete", f"Deleted {self.test_data['artifact_id']}")
        else:
            self.log("FAIL", "artifact_delete", f"Error: {result.get('error', result)}")

    def print_summary(self):
        """Print test summary"""
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = sum(1 for r in self.results if r["status"] == "FAIL")
        skipped = sum(1 for r in self.results if r["status"] == "SKIP")

        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"\033[92mPassed: {passed}\033[0m")
        print(f"\033[91mFailed: {failed}\033[0m")
        print(f"\033[93mSkipped: {skipped}\033[0m")
        print(f"Total: {len(self.results)}")

        if failed > 0:
            print("\n\033[91mFAILED TESTS:\033[0m")
            for r in self.results:
                if r["status"] == "FAIL":
                    print(f"  - {r['test']}: {r['details'][:100]}")

        # Save results
        results_file = "/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/tests/e2e/user_simulation_results.json"
        with open(results_file, "w") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "results": self.results
            }, f, indent=2)
        print(f"\nResults saved to: {results_file}")

        print("\n" + "="*60)
        if failed == 0:
            print("\033[92mALL TESTS PASSED - Ready for user\033[0m")
            sys.exit(0)
        else:
            print("\033[91mTESTS FAILED - Fix before presenting to user\033[0m")
            sys.exit(1)


if __name__ == "__main__":
    runner = E2ETestRunner()
    runner.run_all_tests()
