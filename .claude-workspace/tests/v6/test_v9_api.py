#!/usr/bin/env python3
"""
Quick test for V9 API parameters: edge_types and include_edges.
"""

import os
import sys
from pathlib import Path

# Load env
DEPLOY_DIR = Path(__file__).parent.parent.parent / "deployment"
env_file = DEPLOY_DIR / ".env.prod"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)

# Add adapters
LIB_PATH = Path(__file__).parent / "adapters"
sys.path.insert(0, str(LIB_PATH))

from mcp_client import MCPClient


def test_include_edges_param():
    """Test that include_edges parameter returns edge data."""
    print("\n=== Test: include_edges parameter ===")

    client = MCPClient()
    client.initialize()

    try:
        # First, recall without include_edges (should not have edges key)
        response = client.call_tool("recall", {
            "query": "project decision",
            "limit": 5,
            "include_edges": False
        })

        print(f"Without include_edges: success={response.success}")
        if response.success:
            has_edges = "edges" in response.data
            print(f"  Has 'edges' key: {has_edges}")
            assert not has_edges, "Should NOT have edges when include_edges=False"

        # Now with include_edges=True
        response = client.call_tool("recall", {
            "query": "project decision",
            "limit": 5,
            "include_edges": True
        })

        print(f"With include_edges=True: success={response.success}")
        if response.success:
            has_edges = "edges" in response.data
            print(f"  Has 'edges' key: {has_edges}")
            if has_edges:
                print(f"  Edge count: {len(response.data['edges'])}")
                if response.data['edges']:
                    print(f"  Sample edge: {response.data['edges'][0]}")
            # Should have edges key even if empty
            assert has_edges, "Should HAVE edges key when include_edges=True"

        print("PASS: include_edges parameter works correctly")
        return True

    finally:
        client.close()


def test_edge_types_param():
    """Test that edge_types parameter filters graph expansion."""
    print("\n=== Test: edge_types parameter ===")

    client = MCPClient()
    client.initialize()

    try:
        # Recall with specific edge types filter
        response = client.call_tool("recall", {
            "query": "Alice Bob project",
            "limit": 5,
            "edge_types": ["MANAGES", "WORKS_WITH"],
            "include_edges": True
        })

        print(f"With edge_types=['MANAGES', 'WORKS_WITH']: success={response.success}")
        if response.success:
            print(f"  Results: {len(response.data.get('results', []))}")
            print(f"  Related: {len(response.data.get('related', []))}")
            edges = response.data.get('edges', [])
            print(f"  Edges: {len(edges)}")

            # Verify edges are filtered (if any)
            for edge in edges:
                edge_type = edge.get('type')
                print(f"    Edge type: {edge_type}")
                if edge_type:
                    assert edge_type in ["MANAGES", "WORKS_WITH"], f"Unexpected edge type: {edge_type}"

        print("PASS: edge_types parameter works correctly")
        return True

    finally:
        client.close()


def test_recall_basic():
    """Basic recall test to verify server is responding."""
    print("\n=== Test: Basic recall ===")

    client = MCPClient()
    client.initialize()

    try:
        response = client.call_tool("recall", {
            "query": "test",
            "limit": 3
        })

        print(f"Basic recall: success={response.success}")
        if response.success:
            print(f"  Results: {len(response.data.get('results', []))}")
            print(f"  Related: {len(response.data.get('related', []))}")
            print(f"  Entities: {len(response.data.get('entities', []))}")
        else:
            print(f"  Error: {response.error}")

        return response.success

    finally:
        client.close()


def main():
    print("=" * 60)
    print("V9 API Parameter Tests")
    print("=" * 60)

    # Run tests
    tests = [
        test_recall_basic,
        test_include_edges_param,
        test_edge_types_param,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"FAIL: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
