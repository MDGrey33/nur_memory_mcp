#!/usr/bin/env python3
"""
Test event extraction with varying document ambiguity levels.
"""

import json
import requests
import time
from datetime import datetime

MCP_URL = "http://localhost:3001/mcp/"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream"
}

TEST_DOCS = [
    {
        "name": "Clear Meeting (LOW ambiguity)",
        "ambiguity": "LOW",
        "expected_events": "6+",
        "params": {
            "artifact_type": "transcript",
            "source_system": "manual",
            "source_id": "test-low-ambiguity",
            "title": "Project Alpha Kickoff Meeting",
            "content": """Project Alpha Kickoff Meeting - December 28, 2025
Attendees: Sarah (PM), John (Dev Lead), Maria (Designer)

Sarah: Let's establish our commitments for Q1.

John: I commit to delivering the API by January 15th. The backend team will have all endpoints ready.

Maria: I'll have the design system finalized by January 10th.

Sarah: Great. We've decided to use PostgreSQL for the database instead of MongoDB.

John: There's a risk - we're waiting on security audit results. If delayed, we might miss January 15th.

Sarah: Maria, please schedule a follow-up with security for Tuesday.

Maria: Will do. I'll send the invite today.

Action Items:
- John: API delivery by Jan 15
- Maria: Design system by Jan 10
- Maria: Schedule security meeting"""
        }
    },
    {
        "name": "Ambiguous Email (MEDIUM ambiguity)",
        "ambiguity": "MEDIUM",
        "expected_events": "2-4",
        "params": {
            "artifact_type": "email",
            "source_system": "gmail",
            "source_id": "test-medium-ambiguity",
            "title": "Re: Project Status",
            "content": """From: mike@company.com
Subject: Re: Project Status

Hey team,

So I was thinking about what we discussed yesterday. The client seemed interested but I'm not 100% sure they're on board.

Tom mentioned something about maybe pushing the deadline, but nothing confirmed.

The budget situation is complicated. Finance said they'd look into it.

I think we're going with option B? Someone should clarify.

- Mike

---
From: lisa@company.com

I thought we agreed on option A? Let's confirm.

---
From: tom@company.com

Re: deadline - I said we MIGHT need to discuss it, not that we're pushing."""
        }
    },
    {
        "name": "Casual Slack (HIGH ambiguity)",
        "ambiguity": "HIGH",
        "expected_events": "0-2",
        "params": {
            "artifact_type": "chat",
            "source_system": "slack",
            "source_id": "test-high-ambiguity",
            "title": "dev-team channel",
            "content": """#dev-team - December 28, 2025

[10:15] @alex: yo anyone looked at that bug yet?
[10:16] @jordan: which one lol there's like 50
[10:17] @alex: the login thing
[10:18] @jordan: oh yeah. might be the session timeout thing?
[10:19] @alex: maybe idk
[10:20] @sam: I can take a look later I guess
[10:21] @alex: cool thx
[10:25] @jordan: btw we should prob talk about the refactor
[10:26] @alex: yeah for sure
[10:30] @alex: let's do it next week maybe?
[10:31] @jordan: 👍"""
        }
    }
]


class MCPClient:
    def __init__(self, url):
        self.url = url
        self.session_id = None
        self.request_id = 0

    def _next_id(self):
        self.request_id += 1
        return self.request_id

    def _send(self, method, params=None):
        headers = HEADERS.copy()
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._next_id(),
            "params": params or {}
        }

        resp = requests.post(self.url, headers=headers, json=payload, timeout=30)
        if "Mcp-Session-Id" in resp.headers:
            self.session_id = resp.headers["Mcp-Session-Id"]

        if resp.status_code == 200:
            for line in resp.text.split('\n'):
                if line.startswith('data:'):
                    return json.loads(line[5:].strip())
        return {"error": f"HTTP {resp.status_code}"}

    def init(self):
        result = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "ambiguity-test", "version": "1.0"},
            "capabilities": {}
        })
        if "result" in result:
            self._send("notifications/initialized", {})
            return True
        return False

    def call_tool(self, name, args):
        result = self._send("tools/call", {"name": name, "arguments": args})
        if "result" in result and "content" in result["result"]:
            for c in result["result"]["content"]:
                if c.get("type") == "text":
                    return json.loads(c["text"])
        return result


def main():
    print("="*60)
    print("EVENT EXTRACTION AMBIGUITY TEST")
    print("="*60)
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Server: {MCP_URL}")
    print()

    client = MCPClient(MCP_URL)
    if not client.init():
        print("ERROR: Failed to connect to MCP server")
        return

    print("Connected to MCP server\n")

    results = []

    for doc in TEST_DOCS:
        print("-"*60)
        print(f"Testing: {doc['name']}")
        print(f"Expected events: {doc['expected_events']}")
        print("-"*60)

        # Ingest
        print("  Ingesting...", end=" ", flush=True)
        ingest_result = client.call_tool("artifact_ingest", doc["params"])

        if "error" in ingest_result:
            print(f"ERROR: {ingest_result['error']}")
            continue

        artifact_id = ingest_result.get("artifact_id")
        print(f"OK ({artifact_id})")

        # Wait for extraction
        print("  Waiting for extraction...", end=" ", flush=True)
        for i in range(15):
            time.sleep(2)
            status = client.call_tool("job_status", {"artifact_id": artifact_id})
            job_status = status.get("status", "UNKNOWN")
            if job_status == "DONE":
                print(f"DONE ({(i+1)*2}s)")
                break
            elif job_status == "FAILED":
                print(f"FAILED: {status.get('last_error_message')}")
                break
        else:
            print("TIMEOUT")

        # Get events
        events_result = client.call_tool("event_list", {"artifact_id": artifact_id})
        events = events_result.get("events", [])
        total = events_result.get("total", 0)

        print(f"  Events extracted: {total}")

        if events:
            # Calculate average confidence
            confidences = [e.get("confidence", 0) for e in events]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0
            print(f"  Avg confidence: {avg_conf:.0%}")

            # List events
            print("  Events:")
            for e in events:
                cat = e.get("category", "?")
                narr = e.get("narrative", "?")[:60]
                conf = e.get("confidence", 0)
                print(f"    [{cat}] {narr}... ({conf:.0%})")

        results.append({
            "name": doc["name"],
            "ambiguity": doc["ambiguity"],
            "expected": doc["expected_events"],
            "actual": total,
            "avg_confidence": avg_conf if events else 0
        })
        print()

    # Summary
    print("="*60)
    print("SUMMARY")
    print("="*60)
    print(f"{'Document':<35} {'Ambiguity':<10} {'Expected':<10} {'Actual':<8} {'Conf':<8}")
    print("-"*60)
    for r in results:
        print(f"{r['name']:<35} {r['ambiguity']:<10} {r['expected']:<10} {r['actual']:<8} {r['avg_confidence']:.0%}")
    print("="*60)


if __name__ == "__main__":
    main()
