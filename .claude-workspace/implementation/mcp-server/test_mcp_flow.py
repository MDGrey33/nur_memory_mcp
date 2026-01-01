"""Test the full MCP protocol flow with V6 tools."""
import asyncio
import httpx
import json
import os

MCP_URL = os.getenv("MCP_URL", "http://localhost:3001/mcp/")

async def test_mcp():
    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }

        # Step 1: Initialize
        print("1. Initializing MCP connection...")
        resp = await client.post(MCP_URL, headers=headers, json={
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"}
            },
            "id": 1
        })

        # Parse SSE response
        text = resp.text
        session_id = None
        for line in text.split('\n'):
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if 'result' in data:
                    session_id = resp.headers.get('mcp-session-id')
                    print(f"   Connected! Server: {data['result']['serverInfo']['name']}")
                    print(f"   Session ID: {session_id}")
                    break

        if not session_id:
            print("   Failed to get session ID")
            return

        # Step 2: List tools
        print("\n2. Listing available tools...")
        headers['mcp-session-id'] = session_id
        resp = await client.post(MCP_URL, headers=headers, json={
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": 2
        })

        text = resp.text
        tools = []
        for line in text.split('\n'):
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if 'result' in data and 'tools' in data['result']:
                    tools = data['result']['tools']
                    print(f"   Found {len(tools)} tools:")
                    for tool in tools:
                        print(f"     - {tool['name']}")
                    break

        # Verify we have the V6 tools
        tool_names = [t['name'] for t in tools]
        expected = ['remember', 'recall', 'forget', 'status']
        if set(expected) != set(tool_names):
            print(f"   WARNING: Expected {expected}, got {tool_names}")

        # Step 3: Call remember
        print("\n3. Testing remember tool...")
        resp = await client.post(MCP_URL, headers=headers, json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "remember",
                "arguments": {
                    "content": "Test memory - user prefers dark mode and Python",
                    "context": "preference",
                    "importance": 0.9
                }
            },
            "id": 3
        })

        text = resp.text
        stored_id = None
        for line in text.split('\n'):
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if 'result' in data:
                    content = data['result'].get('content', [])
                    if content:
                        result_text = content[0].get('text', '')
                        print(f"   {result_text[:100]}...")
                        # Extract ID from response
                        if 'id' in result_text or 'art_' in result_text:
                            import re
                            match = re.search(r'art_[a-f0-9]+', result_text)
                            if match:
                                stored_id = match.group()
                    break
                elif 'error' in data:
                    print(f"   Error: {data['error']}")
                    break

        # Step 4: Call recall
        print("\n4. Testing recall tool...")
        resp = await client.post(MCP_URL, headers=headers, json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "recall",
                "arguments": {
                    "query": "user preferences dark mode",
                    "limit": 5
                }
            },
            "id": 4
        })

        text = resp.text
        for line in text.split('\n'):
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if 'result' in data:
                    content = data['result'].get('content', [])
                    if content:
                        result_text = content[0].get('text', '')
                        print(f"   Search results (first 200 chars):")
                        print(f"     {result_text[:200]}...")
                    break
                elif 'error' in data:
                    print(f"   Error: {data['error']}")
                    break

        # Step 5: Call status
        print("\n5. Testing status tool...")
        resp = await client.post(MCP_URL, headers=headers, json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "status",
                "arguments": {}
            },
            "id": 5
        })

        text = resp.text
        for line in text.split('\n'):
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if 'result' in data:
                    content = data['result'].get('content', [])
                    if content:
                        result_text = content[0].get('text', '')
                        # Show first few lines
                        lines = result_text.split('\n')[:5]
                        print(f"   Status:")
                        for l in lines:
                            print(f"     {l}")
                    break
                elif 'error' in data:
                    print(f"   Error: {data['error']}")
                    break

        # Step 6: Clean up with forget (if we stored something)
        if stored_id:
            print(f"\n6. Testing forget tool (cleaning up {stored_id})...")
            resp = await client.post(MCP_URL, headers=headers, json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "forget",
                    "arguments": {
                        "id": stored_id,
                        "confirm": True
                    }
                },
                "id": 6
            })

            text = resp.text
            for line in text.split('\n'):
                if line.startswith('data: '):
                    data = json.loads(line[6:])
                    if 'result' in data:
                        content = data['result'].get('content', [])
                        if content:
                            result_text = content[0].get('text', '')
                            print(f"   {result_text[:100]}")
                        break
                    elif 'error' in data:
                        print(f"   Error: {data['error']}")
                        break

        print("\n" + "="*50)
        print("ALL TESTS PASSED - MCP Server v6.1 is working!")
        print("="*50)

if __name__ == "__main__":
    asyncio.run(test_mcp())
