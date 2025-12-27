#!/usr/bin/env python3
"""
Test script to ingest sample meeting documents and view extracted events.

Usage:
    python test_samples.py [document_name]

    document_name: sprint, qbr, retro, incident (or 'all')
"""

import sys
import os
import time
import json
import requests
from pathlib import Path

MCP_BASE = "http://localhost:3000"
MCP_URL = "http://localhost:3000/mcp/"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream"
}

# Session state
session_id = None
request_id = 0

DOCUMENTS = {
    "sprint": {
        "file": "sprint_planning.md",
        "title": "Sprint 14 Planning Meeting",
        "type": "note",
        "participants": ["Marcus Chen", "Priya Sharma", "Jake Wilson", "Lisa Park"]
    },
    "qbr": {
        "file": "quarterly_business_review.md",
        "title": "Q4 2024 Business Review",
        "type": "note",
        "participants": ["Sarah Mitchell", "David Park", "Emma Rodriguez", "Tom Bradley", "Rachel Kim"]
    },
    "retro": {
        "file": "project_retrospective.md",
        "title": "Project Phoenix Post-Mortem",
        "type": "note",
        "participants": ["Amanda Foster", "Derek", "Jessica", "Chris"]
    },
    "incident": {
        "file": "customer_incident_review.md",
        "title": "Payment Processing Outage Post-Mortem",
        "type": "note",
        "participants": ["Mike Chen", "Anna Kowalski", "James Wright"]
    }
}

def initialize_session():
    """Initialize MCP session (required for MCP protocol)."""
    global session_id, request_id

    payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "id": 1,
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "sample-test-client", "version": "1.0"},
            "capabilities": {}
        }
    }

    try:
        resp = requests.post(MCP_URL, headers=HEADERS, json=payload, timeout=30)
        if "Mcp-Session-Id" in resp.headers:
            session_id = resp.headers["Mcp-Session-Id"]

        # Send initialized notification
        notify_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "id": 2,
            "params": {}
        }
        headers = HEADERS.copy()
        headers["Mcp-Session-Id"] = session_id
        requests.post(MCP_URL, headers=headers, json=notify_payload, timeout=10)

        return session_id is not None
    except Exception as e:
        print(f"Failed to initialize session: {e}")
        return False

def call_tool(tool_name: str, params: dict) -> dict:
    """Call an MCP tool via JSON-RPC."""
    global request_id
    request_id += 1

    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": params
        }
    }

    headers = HEADERS.copy()
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    response = requests.post(
        MCP_URL,
        json=payload,
        headers=headers,
        timeout=60
    )

    # Parse SSE response
    for line in response.text.split("\n"):
        if line.startswith("data: "):
            data = json.loads(line[6:])
            if "result" in data:
                content = data["result"].get("content", [])
                if content and content[0].get("type") == "text":
                    return json.loads(content[0]["text"])
    return {}

def ingest_document(doc_key: str) -> dict:
    """Ingest a sample document."""
    doc = DOCUMENTS[doc_key]
    doc_path = Path(__file__).parent / doc["file"]

    with open(doc_path) as f:
        content = f.read()

    print(f"\n📄 Ingesting: {doc['title']}")
    print(f"   Size: {len(content)} chars")

    result = call_tool("artifact_ingest", {
        "artifact_type": doc["type"],
        "source_system": "sample-test",
        "content": content,
        "title": doc["title"],
        "source_id": f"sample-{doc_key}-{int(time.time())}",
        "participants": doc["participants"]
    })

    if "artifact_uid" in result:
        print(f"   ✅ Ingested: {result['artifact_uid']}")
        print(f"   Job ID: {result.get('job_id', 'N/A')}")
    else:
        print(f"   ❌ Failed: {result}")

    return result

def wait_for_extraction(artifact_uid: str, timeout: int = 120) -> bool:
    """Wait for event extraction to complete."""
    print(f"\n⏳ Waiting for extraction...")
    start = time.time()

    while time.time() - start < timeout:
        result = call_tool("job_status", {"artifact_uid": artifact_uid})
        status = result.get("status", "UNKNOWN")
        elapsed = int(time.time() - start)

        print(f"   Status: {status} ({elapsed}s)", end="\r")

        if status == "DONE":
            print(f"\n   ✅ Extraction completed in {elapsed}s")
            return True
        elif status == "FAILED":
            print(f"\n   ❌ Extraction failed: {result.get('last_error_message')}")
            return False

        time.sleep(3)

    print(f"\n   ⚠️ Timeout after {timeout}s")
    return False

def show_events(artifact_uid: str):
    """Display extracted events."""
    result = call_tool("event_list_for_artifact", {
        "artifact_uid": artifact_uid,
        "include_evidence": True
    })

    events = result.get("events", [])
    print(f"\n📋 Extracted {len(events)} Events:\n")

    # Group by category
    by_category = {}
    for event in events:
        cat = event.get("category", "Unknown")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(event)

    for category, cat_events in sorted(by_category.items()):
        print(f"═══ {category} ({len(cat_events)}) ═══")
        for e in cat_events:
            narrative = e.get("narrative", "")[:80]
            confidence = e.get("confidence", 0)
            actors = e.get("actors", "[]")
            if isinstance(actors, str):
                try:
                    actors = json.loads(actors)
                except:
                    actors = []

            actor_names = [a.get("ref", a) if isinstance(a, dict) else str(a) for a in actors]
            actor_str = ", ".join(actor_names) if actor_names else "—"

            print(f"  • {narrative}...")
            print(f"    Actors: {actor_str} | Confidence: {confidence:.0%}")

            # Show evidence
            evidence = e.get("evidence", [])
            if evidence:
                quote = evidence[0].get("quote", "")[:60]
                print(f"    Evidence: \"{quote}...\"")
            print()

    return events

def test_document(doc_key: str):
    """Full test of a single document."""
    if doc_key not in DOCUMENTS:
        print(f"❌ Unknown document: {doc_key}")
        print(f"   Available: {', '.join(DOCUMENTS.keys())}")
        return

    print(f"\n{'='*60}")
    print(f"Testing: {DOCUMENTS[doc_key]['title']}")
    print('='*60)

    # Ingest
    result = ingest_document(doc_key)
    if "artifact_uid" not in result:
        return

    artifact_uid = result["artifact_uid"]

    # Wait for extraction
    if not wait_for_extraction(artifact_uid):
        return

    # Show events
    events = show_events(artifact_uid)

    print(f"\n{'='*60}")
    print(f"Summary: {len(events)} events extracted from {DOCUMENTS[doc_key]['title']}")
    print('='*60)

def main():
    if len(sys.argv) < 2:
        print("Sample Meeting Documents Test")
        print("-" * 40)
        print("\nAvailable documents:")
        for key, doc in DOCUMENTS.items():
            print(f"  {key:10} - {doc['title']}")
        print("\nUsage: python test_samples.py <document>")
        print("       python test_samples.py all")
        return

    # Initialize MCP session first
    print("🔌 Initializing MCP session...")
    if not initialize_session():
        print("❌ Failed to initialize MCP session")
        return
    print(f"✅ Session initialized: {session_id[:16]}...")

    doc_key = sys.argv[1].lower()

    if doc_key == "all":
        for key in DOCUMENTS:
            test_document(key)
            print("\n")
    else:
        test_document(doc_key)

if __name__ == "__main__":
    main()
