"""
Event worker entry point.

Usage:
    python -m src.worker
"""

import sys
import logging
import asyncio
from pathlib import Path

# Add src to path
src_dir = Path(__file__).parent.parent
sys.path.insert(0, str(src_dir))

from worker.event_worker import EventWorker
from config import load_config
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("worker_main")


async def main():
    """Main worker entry point."""
    try:
        # Load configuration
        config = load_config()

        logger.info("=" * 60)
        logger.info("Starting Event Worker")
        logger.info("=" * 60)
        logger.info(f"  Worker ID: {config.worker_id or 'auto-generated'}")
        logger.info(f"  Poll Interval: {config.poll_interval_ms}ms")
        logger.info(f"  Max Attempts: {config.event_max_attempts}")
        logger.info(f"  Event Model: {config.openai_event_model}")
        logger.info(f"  Postgres DSN: {config.events_db_dsn.split('@')[1] if '@' in config.events_db_dsn else config.events_db_dsn}")
        logger.info("=" * 60)

        # Create worker
        worker = EventWorker(config)

        # Run worker
        await worker.run()

    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
