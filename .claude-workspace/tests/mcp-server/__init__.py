"""
MCP Server V3 test suite.

Test coverage:
- PostgresClient: Connection pooling, query execution, transactions
- EventExtractionService: LLM-based event extraction and validation
- JobQueueService: Job queue management, retry logic, atomic writes
- Event Tools: MCP tool functions for querying events
- E2E: End-to-end integration scenarios
"""

__version__ = "3.0.0"
