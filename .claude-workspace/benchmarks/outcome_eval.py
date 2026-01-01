#!/usr/bin/env python3
"""
Simple LLM-Based Outcome Evaluation for MCP Memory System

One test that:
1. Stores related documents
2. Queries the system
3. Uses an LLM to verify expected outcomes
4. Returns clear pass/fail
"""

import asyncio
import json
import os
import sys
import httpx
from openai import AsyncOpenAI

# MCP Server config
MCP_URL = os.getenv("MCP_URL", "http://localhost:3001")

# Test Documents - a web of related information
# Using unique names to avoid collisions with benchmark data
DOCUMENTS = [
    {
        "id": "outcome_test/meeting.txt",
        "context": "meeting",
        "content": """Meeting Notes - Zephyr Project Kickoff
Date: December 10th, 2025
Attendees: Priya Sharma, Marcus Weber, Elena Rodriguez

Discussion Summary:
Priya presented the design for the new Zephyr analytics dashboard.
She committed to deliver the GraphQL API by December 20th.

Marcus will handle the MongoDB database schema design.
He mentioned MongoDB would be the best fit for our analytics data.

Decision: Use GraphQL architecture with MongoDB backend.
Elena approved the timeline and will coordinate with the data science team.

Action Items:
- Priya: Complete GraphQL API endpoints by December 20th
- Marcus: Finalize MongoDB schema by December 15th
- Elena: Brief data science team on API contract"""
    },
    {
        "id": "outcome_test/email.txt",
        "context": "email",
        "content": """From: Marcus Weber <marcus@zephyrtech.io>
To: Priya Sharma <priya@zephyrtech.io>
Subject: RE: Zephyr API Progress Check
Date: December 15th, 2025

Hey Priya,

Quick check on the GraphQL API progress for Zephyr. I've finished the MongoDB
schema on my end - all collections are ready for the analytics data.

Let me know if you need the collection definitions or any adjustments
to support your resolver designs.

The schema includes:
- events collection
- metrics collection
- dashboards collection

All with proper indexes for the aggregation queries you mentioned.

Cheers,
Marcus"""
    },
    {
        "id": "outcome_test/decision.txt",
        "context": "decision",
        "content": """Architecture Decision Record: Zephyr Analytics Tech Stack

Decision ID: ADR-2025-047
Date: December 10th, 2025
Status: Approved

Context:
We need to build the Zephyr analytics dashboard with API backend.

Decision:
- Backend: GraphQL API (owned by Priya Sharma)
- Database: MongoDB (owned by Marcus Weber)
- Architecture: Event-driven pattern

Rationale:
- Team has strong GraphQL experience
- MongoDB offers flexibility for analytics data
- Event-driven allows real-time updates

Stakeholders:
- Priya Sharma (API Lead)
- Marcus Weber (Database Lead)
- Elena Rodriguez (Project Manager)
- Kevin Chang (Data Science Lead)

Approved by: Elena Rodriguez"""
    }
]

# Query that requires finding connections
QUERY = "What is Priya working on for the Zephyr project and who else is involved?"

# Expected outcomes - what the system should find
EXPECTED_OUTCOMES = [
    "Priya is working on a GraphQL API for Zephyr analytics dashboard",
    "The API deadline is December 20th",
    "Marcus Weber is involved with the MongoDB database schema",
    "Elena Rodriguez is involved as project manager or stakeholder",
    "MongoDB was chosen as the database",
]

PASS_THRESHOLD = 0.8  # Need 4/5 to pass


class MCPClient:
    """Simple MCP client using Streamable HTTP transport."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session_id = None
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _parse_sse_response(self, text: str) -> dict:
        """Parse SSE response to extract JSON-RPC result."""
        for line in text.split('\n'):
            if line.startswith('data: '):
                try:
                    return json.loads(line[6:])
                except json.JSONDecodeError:
                    pass
        return {}

    async def initialize(self) -> bool:
        """Initialize MCP session."""
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.post(
                f'{self.base_url}/mcp/',
                headers={
                    'Content-Type': 'application/json',
                    'Accept': 'application/json, text/event-stream'
                },
                json={
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "outcome-eval", "version": "1.0"}
                    }
                }
            )

            self.session_id = response.headers.get('mcp-session-id')
            result = self._parse_sse_response(response.text)

            if 'error' in result:
                print(f"MCP initialization failed: {result['error']}")
                return False

            return True

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Call an MCP tool and return result."""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream'
        }
        if self.session_id:
            headers['mcp-session-id'] = self.session_id

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.post(
                f'{self.base_url}/mcp/',
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "tools/call",
                    "params": {
                        "name": name,
                        "arguments": arguments
                    }
                }
            )

            result = self._parse_sse_response(response.text)

            if 'error' in result:
                raise Exception(f"MCP Error: {result['error']}")

            return result.get('result', {})


async def store_documents(mcp: MCPClient, debug: bool = False) -> bool:
    """Store test documents via MCP remember()."""
    print("Storing documents...")

    for doc in DOCUMENTS:
        try:
            result = await mcp.call_tool("remember", {
                "content": doc["content"],
                "context": doc.get("context", "document"),
                "metadata": {"source_id": doc["id"]}
            })

            # Check for errors in the response
            result_text = ""
            if isinstance(result, dict) and "content" in result:
                for item in result.get("content", []):
                    if item.get("type") == "text":
                        result_text = item.get("text", "")
                        break

            if "error" in result_text.lower():
                print(f"  Error storing {doc['id']}: {result_text}")
                return False

            if debug:
                print(f"  remember() returned: {result_text[:300]}")
            print(f"  Stored: {doc['id']}")
        except Exception as e:
            print(f"  Error storing {doc['id']}: {e}")
            return False

    # Wait for event extraction
    print("  Waiting for event extraction...")
    await asyncio.sleep(5)

    return True


async def query_system(mcp: MCPClient, query: str, debug: bool = False) -> str:
    """Query via MCP recall() with graph expansion."""
    print(f"Querying: {query}")

    result = await mcp.call_tool("recall", {
        "query": query,
        "limit": 10,
        "expand": True
    })

    response_json = json.dumps(result, indent=2, default=str)

    if debug:
        print("\n--- DEBUG: MCP Response ---")
        print(response_json[:2000])
        print("--- END DEBUG ---\n")

    return response_json


async def evaluate_with_llm(response: str, outcomes: list[str]) -> dict:
    """Use LLM to check if expected outcomes are present in response."""
    print("Evaluating with LLM...")

    client = AsyncOpenAI()

    prompt = f"""You are evaluating if an information retrieval system found the expected information.

The system was asked: "{QUERY}"

System Response:
{response}

Expected Outcomes to check:
{chr(10).join(f'{i+1}. {o}' for i, o in enumerate(outcomes))}

For each expected outcome, determine:
- FOUND: The information is clearly present in the response
- PARTIAL: Related information exists but incomplete
- MISSING: Not found in the response

Return JSON only (no markdown):
{{
  "outcomes": [
    {{"id": 1, "status": "FOUND", "evidence": "brief quote showing this"}},
    {{"id": 2, "status": "PARTIAL", "evidence": "what was found"}},
    {{"id": 3, "status": "MISSING", "evidence": null}},
    ...
  ],
  "found_count": <number of FOUND>,
  "partial_count": <number of PARTIAL>,
  "missing_count": <number of MISSING>,
  "pass": <true if (found + partial) / total >= {PASS_THRESHOLD}>,
  "reasoning": "one sentence explaining the overall result"
}}"""

    try:
        completion = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )

        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"LLM evaluation error: {e}")
        return {
            "outcomes": [],
            "found_count": 0,
            "partial_count": 0,
            "missing_count": len(outcomes),
            "pass": False,
            "reasoning": f"Evaluation failed: {e}"
        }


def print_results(result: dict, outcomes: list[str]):
    """Print formatted results."""
    print("\n" + "=" * 50)
    print("RESULTS")
    print("=" * 50 + "\n")

    for outcome_result in result.get("outcomes", []):
        idx = outcome_result["id"] - 1
        status = outcome_result["status"]

        if status == "FOUND":
            icon = "\033[92m✓\033[0m"  # Green check
        elif status == "PARTIAL":
            icon = "\033[93m◐\033[0m"  # Yellow partial
        else:
            icon = "\033[91m✗\033[0m"  # Red X

        outcome_text = outcomes[idx] if idx < len(outcomes) else "Unknown"
        print(f"  {icon} {outcome_text}")

        if outcome_result.get("evidence"):
            print(f"      Evidence: \"{outcome_result['evidence'][:80]}...\"")

    print()
    found = result.get("found_count", 0)
    partial = result.get("partial_count", 0)
    missing = result.get("missing_count", 0)
    total = found + partial + missing

    score = (found + partial) / total if total > 0 else 0

    print(f"Score: {found} found, {partial} partial, {missing} missing")
    print(f"Pass Rate: {score:.0%} (threshold: {PASS_THRESHOLD:.0%})")
    print()

    if result.get("pass"):
        print("\033[92m>>> PASS <<<\033[0m")
    else:
        print("\033[91m>>> FAIL <<<\033[0m")

    print()
    print(f"Reasoning: {result.get('reasoning', 'N/A')}")
    print()


async def cleanup(mcp: MCPClient):
    """Clean up test documents."""
    print("\nCleaning up test documents...")

    for doc in DOCUMENTS:
        try:
            # Query to find the artifact ID
            result = await mcp.call_tool("recall", {
                "query": doc["id"],
                "limit": 1
            })

            # Try to extract artifact ID and delete
            if result and "artifacts" in str(result):
                # Best effort cleanup
                pass
        except:
            pass

    print("Cleanup complete (best effort)")


async def run_evaluation(cleanup_after: bool = False, debug: bool = False) -> bool:
    """Main evaluation runner."""
    print()
    print("=" * 50)
    print("MCP OUTCOME EVALUATION")
    print("=" * 50)
    print()

    # Initialize MCP client
    mcp = MCPClient(MCP_URL)

    print(f"Connecting to MCP at {MCP_URL}...")
    if not await mcp.initialize():
        print("Failed to initialize MCP connection")
        return False
    print("Connected!\n")

    # Store documents
    if not await store_documents(mcp, debug=debug):
        print("Failed to store documents")
        return False

    # Query system
    try:
        response = await query_system(mcp, QUERY, debug=debug)
    except Exception as e:
        print(f"Query failed: {e}")
        return False

    # Evaluate with LLM
    result = await evaluate_with_llm(response, EXPECTED_OUTCOMES)

    # Print results
    print_results(result, EXPECTED_OUTCOMES)

    # Optional cleanup
    if cleanup_after:
        await cleanup(mcp)

    return result.get("pass", False)


def main():
    """Entry point."""
    global MCP_URL
    import argparse

    parser = argparse.ArgumentParser(description="MCP Outcome Evaluation")
    parser.add_argument("--cleanup", action="store_true", help="Clean up test docs after")
    parser.add_argument("--debug", action="store_true", help="Show debug output")
    parser.add_argument("--url", help="MCP server URL (default: http://localhost:3001)")
    args = parser.parse_args()

    # Override URL if provided
    if args.url:
        MCP_URL = args.url

    try:
        success = asyncio.run(run_evaluation(cleanup_after=args.cleanup, debug=args.debug))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nAborted")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
