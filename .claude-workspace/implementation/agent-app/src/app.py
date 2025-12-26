"""
Main application entrypoint and orchestration.

Demonstrates the complete memory flows: bootstrap, append history, write memory, build context.
"""

import asyncio
import logging
from typing import Optional
from .config import AppConfig
from .memory_gateway import ChromaMcpGateway
from .context_builder import ContextBuilder
from .memory_policy import MemoryPolicy
from .models import HistoryTurn, MemoryItem
from .utils import get_iso_timestamp, setup_logging
from .exceptions import MCPMemoryError


logger = logging.getLogger('mcp_memory.app')


class Application:
    """
    Main application orchestrating memory operations.

    Wires together all components and demonstrates the core flows.
    """

    def __init__(self, config: AppConfig):
        """
        Initialize application with configuration.

        Args:
            config: Application configuration
        """
        self.config = config
        self.gateway: Optional[ChromaMcpGateway] = None
        self.context_builder: Optional[ContextBuilder] = None
        self.memory_policy: Optional[MemoryPolicy] = None
        self.running = False

        # Setup logging
        setup_logging(config.log_level)
        logger.info(f"Application initialized with config: {config}")

    async def start(self) -> None:
        """
        Start the application and bootstrap.

        Raises:
            MCPMemoryError: If bootstrap fails
        """
        logger.info("Starting application...")

        try:
            # Initialize gateway
            self.gateway = ChromaMcpGateway(
                mcp_endpoint=self.config.mcp_endpoint
            )

            # Bootstrap: ensure collections exist
            async with self.gateway:
                await self._bootstrap()

                # Initialize other components
                self.context_builder = ContextBuilder(
                    gateway=self.gateway,
                    history_tail_n=self.config.history_tail_n,
                    memory_top_k=self.config.memory_top_k,
                    min_confidence=self.config.memory_confidence_min,
                    token_budget=self.config.context_token_budget
                )

                self.memory_policy = MemoryPolicy(
                    min_confidence=self.config.memory_confidence_min,
                    max_per_window=self.config.memory_max_per_window
                )

                self.running = True
                logger.info("Application ready")

                # Demonstrate flows
                await self._demonstrate_flows()

        except Exception as e:
            logger.error(f"Failed to start application: {e}")
            raise MCPMemoryError(f"Application startup failed: {e}") from e

    async def stop(self) -> None:
        """Stop the application gracefully."""
        logger.info("Stopping application...")
        self.running = False
        logger.info("Application stopped")

    async def _bootstrap(self) -> None:
        """
        Bootstrap the application.

        Ensures required collections exist.

        Raises:
            MCPMemoryError: If bootstrap fails
        """
        logger.info("Bootstrapping application...")

        try:
            await self.gateway.ensure_collections(["history", "memory"])
            logger.info("Bootstrap complete")
        except Exception as e:
            logger.error(f"Bootstrap failed: {e}")
            raise MCPMemoryError(f"Bootstrap failed: {e}") from e

    async def handle_message(
        self,
        conversation_id: str,
        role: str,
        text: str,
        turn_index: int,
        message_id: Optional[str] = None
    ) -> None:
        """
        Handle a conversation message.

        Appends to history and triggers context building if user message.

        Args:
            conversation_id: Conversation identifier
            role: Message role (user, assistant, system)
            text: Message text
            turn_index: Turn index
            message_id: Optional message ID
        """
        logger.debug(f"Handling message: conversation_id={conversation_id}, role={role}")

        try:
            # Append to history
            ts = get_iso_timestamp()
            doc_id = await self.gateway.append_history(
                conversation_id=conversation_id,
                role=role,
                text=text,
                turn_index=turn_index,
                ts=ts,
                message_id=message_id
            )
            logger.info(f"Message stored: {doc_id}")

            # If user message, build context for response
            if role == "user":
                context = await self.context_builder.build_context(
                    conversation_id=conversation_id,
                    latest_user_text=text
                )
                prompt = self.context_builder.format_for_prompt(context)
                logger.info(f"Context built for response generation:\n{prompt}")

        except Exception as e:
            logger.error(f"Failed to handle message: {e}")
            # Don't raise - degrade gracefully

    async def store_memory(
        self,
        text: str,
        memory_type: str,
        confidence: float,
        conversation_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Store a memory if it passes policy checks.

        Args:
            text: Memory text
            memory_type: Memory type (preference, fact, project, decision)
            confidence: Confidence score [0.0, 1.0]
            conversation_id: Optional conversation ID

        Returns:
            Document ID if stored, None if rejected
        """
        logger.debug(f"Attempting to store memory: type={memory_type}, confidence={confidence}")

        try:
            # Policy check: confidence threshold
            if not self.memory_policy.should_store(memory_type, confidence):
                logger.info("Memory rejected by policy (confidence too low)")
                return None

            # Policy check: rate limit
            if conversation_id:
                window_key = MemoryPolicy.generate_window_key(conversation_id)
                if not self.memory_policy.enforce_rate_limit(window_key):
                    logger.info("Memory rejected by policy (rate limit)")
                    return None

            # Store memory
            ts = get_iso_timestamp()
            doc_id = await self.gateway.write_memory(
                text=text,
                memory_type=memory_type,
                confidence=confidence,
                ts=ts,
                conversation_id=conversation_id
            )
            logger.info(f"Memory stored: {doc_id}")
            return doc_id

        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            return None

    async def _demonstrate_flows(self) -> None:
        """
        Demonstrate the core flows with example data.
        """
        logger.info("=== Demonstrating Core Flows ===")

        conversation_id = "demo_conv_001"

        # Flow 1: Append history
        logger.info("--- Flow 1: Append History ---")
        await self.handle_message(
            conversation_id=conversation_id,
            role="user",
            text="Hi, I'm interested in building a memory system using Docker and ChromaDB.",
            turn_index=1
        )

        await self.handle_message(
            conversation_id=conversation_id,
            role="assistant",
            text="I'd be happy to help you build a memory system! ChromaDB is an excellent choice for vector storage.",
            turn_index=2
        )

        # Flow 2: Write memory
        logger.info("--- Flow 2: Write Memory ---")
        await self.store_memory(
            text="User is building a memory system with Docker and ChromaDB",
            memory_type="project",
            confidence=0.9,
            conversation_id=conversation_id
        )

        await self.store_memory(
            text="User prefers Docker-based deployment solutions",
            memory_type="preference",
            confidence=0.85,
            conversation_id=conversation_id
        )

        # Flow 3: Another user message triggers context build
        logger.info("--- Flow 3: Context Build ---")
        await self.handle_message(
            conversation_id=conversation_id,
            role="user",
            text="What are the best practices for persistent storage in Docker?",
            turn_index=3
        )

        # Flow 4: Test rate limiting
        logger.info("--- Flow 4: Test Rate Limiting ---")
        for i in range(5):
            result = await self.store_memory(
                text=f"Test memory {i}",
                memory_type="fact",
                confidence=0.8,
                conversation_id=conversation_id
            )
            if result:
                logger.info(f"Memory {i} stored: {result}")
            else:
                logger.info(f"Memory {i} rejected by policy")

        logger.info("=== Demonstration Complete ===")


async def main():
    """
    Main entry point.
    """
    # Load configuration
    config = AppConfig.from_env()

    # Create and start application
    app = Application(config)

    try:
        await app.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Application error: {e}")
        raise
    finally:
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
