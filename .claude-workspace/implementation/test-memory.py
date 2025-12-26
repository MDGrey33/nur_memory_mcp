#!/usr/bin/env python3
"""
Interactive test script for Chroma MCP Memory V1.
Run this after 'docker compose up -d' to test the memory system.
"""

import asyncio
import httpx
import json
from datetime import datetime
from uuid import uuid4

CHROMA_URL = "http://localhost:8000"

async def main():
    print("=" * 60)
    print("Chroma MCP Memory V1 - Interactive Test")
    print("=" * 60)

    async with httpx.AsyncClient(base_url=CHROMA_URL, timeout=30.0) as client:

        # 1. Health check
        print("\n[1] Health Check")
        resp = await client.get("/api/v1/heartbeat")
        print(f"    ChromaDB Status: {'OK' if resp.status_code == 200 else 'FAILED'}")

        # 2. Create collections
        print("\n[2] Creating Collections")
        for coll in ["history", "memory"]:
            try:
                resp = await client.post("/api/v1/collections", json={
                    "name": coll,
                    "metadata": {"created": datetime.utcnow().isoformat()}
                })
                if resp.status_code == 200:
                    print(f"    Created '{coll}' collection")
                else:
                    print(f"    Collection '{coll}' already exists or error: {resp.text}")
            except Exception as e:
                print(f"    Note: {e}")

        # 3. Add history entries
        print("\n[3] Adding History Entries")
        conversation_id = f"conv_{uuid4().hex[:8]}"
        history_entries = [
            {"role": "user", "text": "Hello, I'm testing the memory system"},
            {"role": "assistant", "text": "Hello! I'm ready to help you test the memory system."},
            {"role": "user", "text": "Can you remember that my favorite color is blue?"},
            {"role": "assistant", "text": "I'll remember that your favorite color is blue."},
        ]

        # Get collection ID
        resp = await client.get(f"/api/v1/collections/history")
        if resp.status_code != 200:
            print("    ERROR: Could not get history collection")
            return
        history_coll = resp.json()

        for i, entry in enumerate(history_entries):
            doc_id = f"{conversation_id}_turn_{i}"
            resp = await client.post(f"/api/v1/collections/history/add", json={
                "ids": [doc_id],
                "documents": [f"{entry['role']}: {entry['text']}"],
                "metadatas": [{
                    "conversation_id": conversation_id,
                    "role": entry["role"],
                    "turn_index": i,
                    "ts": datetime.utcnow().isoformat()
                }]
            })
            print(f"    Added turn {i}: {entry['role'][:4]}... ({resp.status_code})")

        # 4. Add a memory
        print("\n[4] Adding Memory Entry")
        resp = await client.get(f"/api/v1/collections/memory")
        if resp.status_code != 200:
            print("    ERROR: Could not get memory collection")
            return

        memory_id = f"mem_{uuid4().hex[:8]}"
        resp = await client.post(f"/api/v1/collections/memory/add", json={
            "ids": [memory_id],
            "documents": ["User's favorite color is blue"],
            "metadatas": [{
                "type": "preference",
                "confidence": 0.9,
                "ts": datetime.utcnow().isoformat(),
                "conversation_id": conversation_id
            }]
        })
        print(f"    Added memory: 'User's favorite color is blue' ({resp.status_code})")

        # 5. Query history
        print("\n[5] Querying History (last 4 turns)")
        resp = await client.post(f"/api/v1/collections/history/get", json={
            "where": {"conversation_id": conversation_id},
            "limit": 4
        })
        if resp.status_code == 200:
            data = resp.json()
            print(f"    Found {len(data.get('documents', []))} history entries")
            for doc in data.get('documents', [])[:4]:
                print(f"      - {doc[:60]}...")

        # 6. Semantic search on memory
        print("\n[6] Semantic Search: 'What color does the user like?'")
        resp = await client.post(f"/api/v1/collections/memory/query", json={
            "query_texts": ["What color does the user like?"],
            "n_results": 3
        })
        if resp.status_code == 200:
            data = resp.json()
            docs = data.get('documents', [[]])[0]
            distances = data.get('distances', [[]])[0]
            print(f"    Found {len(docs)} matching memories:")
            for doc, dist in zip(docs, distances):
                print(f"      - {doc} (distance: {dist:.4f})")

        # 7. Verify persistence info
        print("\n[7] Collection Stats")
        for coll in ["history", "memory"]:
            resp = await client.get(f"/api/v1/collections/{coll}/count")
            if resp.status_code == 200:
                print(f"    {coll}: {resp.json()} documents")

        print("\n" + "=" * 60)
        print("TEST COMPLETE")
        print("=" * 60)
        print(f"\nConversation ID: {conversation_id}")
        print("\nTo verify persistence:")
        print("  1. docker compose down")
        print("  2. docker compose up -d")
        print("  3. Run this script again - data should still exist")
        print("\nTo clean up:")
        print("  docker compose down -v")

if __name__ == "__main__":
    asyncio.run(main())
