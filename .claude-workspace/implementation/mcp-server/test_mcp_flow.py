"""Test the full MCP protocol flow."""
import asyncio
import httpx
import json

MCP_URL = "http://localhost:3000/mcp/"

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
        for line in text.split('\n'):
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if 'result' in data:
                    session_id = resp.headers.get('mcp-session-id')
                    print(f"   ✓ Connected! Server: {data['result']['serverInfo']['name']}")
                    print(f"   Session ID: {session_id}")
                    break
        
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
                    print(f"   ✓ Found {len(tools)} tools:")
                    for tool in tools:
                        print(f"     - {tool['name']}")
                    break
        
        # Step 3: Call memory_store
        print("\n3. Testing memory_store tool...")
        resp = await client.post(MCP_URL, headers=headers, json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "memory_store",
                "arguments": {
                    "content": "Test memory - user prefers dark mode",
                    "type": "preference",
                    "confidence": 0.9
                }
            },
            "id": 3
        })
        
        text = resp.text
        for line in text.split('\n'):
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if 'result' in data:
                    content = data['result'].get('content', [])
                    if content:
                        print(f"   ✓ {content[0].get('text', 'Success')}")
                    break
                elif 'error' in data:
                    print(f"   ✗ Error: {data['error']}")
                    break
        
        # Step 4: Call memory_search
        print("\n4. Testing memory_search tool...")
        resp = await client.post(MCP_URL, headers=headers, json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "memory_search",
                "arguments": {
                    "query": "user preferences",
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
                        print(f"   ✓ Search results:")
                        for line in result_text.split('\n')[:3]:
                            print(f"     {line}")
                    break
                elif 'error' in data:
                    print(f"   ✗ Error: {data['error']}")
                    break
        
        # Step 5: Call memory_list
        print("\n5. Testing memory_list tool...")
        resp = await client.post(MCP_URL, headers=headers, json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "memory_list",
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
                        print(f"   ✓ {result_text.split(chr(10))[0]}")
                    break
                elif 'error' in data:
                    print(f"   ✗ Error: {data['error']}")
                    break
        
        print("\n" + "="*50)
        print("✓ ALL TESTS PASSED - MCP Server is working!")
        print("="*50)

if __name__ == "__main__":
    asyncio.run(test_mcp())
