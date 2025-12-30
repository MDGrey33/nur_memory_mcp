"""
Pytest configuration and fixtures for MCP Memory Server Playwright tests.

Provides:
- Environment-aware configuration (prod/staging/test)
- Port mapping for different environments
- MCPClient fixture for JSON-RPC communication
- Playwright browser fixtures
- Production safety checks
- Support for both sync and async tests
"""

import os
import sys
import pytest
import asyncio
from dataclasses import dataclass
from typing import Dict, Generator, Optional, Any
from pathlib import Path

from playwright.sync_api import (
    Playwright,
    Browser,
    BrowserContext,
    Page,
    sync_playwright,
)

# Add lib directory to Python path
lib_path = Path(__file__).parent / "lib"
sys.path.insert(0, str(lib_path))


# ============================================================================
# Environment Configuration
# ============================================================================

@dataclass
class EnvironmentConfig:
    """
    Environment-specific configuration for test execution.

    Attributes:
        name: Environment name (prod, staging, test)
        mcp_port: Port for MCP server HTTP endpoint
        mcp_https_port: Port for MCP server HTTPS endpoint
        chroma_port: Port for ChromaDB service
        postgres_port: Port for PostgreSQL service
        pgadmin_port: Port for pgAdmin web interface
        inspector_port: Port for MCP Inspector
        mcp_url: Full URL for MCP server endpoint
        inspector_url: Full URL for MCP Inspector
        chroma_url: Full URL for ChromaDB
        database_url: PostgreSQL connection string
    """
    name: str
    mcp_port: int
    mcp_https_port: int
    chroma_port: int
    postgres_port: int
    pgadmin_port: int
    inspector_port: int
    mcp_url: str
    inspector_url: str
    chroma_url: str
    database_url: str

    @classmethod
    def from_env(cls) -> "EnvironmentConfig":
        """
        Load configuration from environment variables.

        Environment variable precedence:
        1. Explicit env vars (e.g., MCP_PORT, MCP_URL)
        2. TEST_ENVIRONMENT-based defaults
        3. Test environment defaults

        Returns:
            EnvironmentConfig instance with all settings populated
        """
        env_name = os.getenv("TEST_ENVIRONMENT", "test").lower()

        # Port mapping by environment
        # Production: base ports
        # Staging: +100 offset
        # Test: +200 offset
        port_configs: Dict[str, Dict[str, int]] = {
            "prod": {
                "mcp": 3001,
                "mcp_https": 3443,
                "chroma": 8001,
                "postgres": 5432,
                "pgadmin": 5050,
                "inspector": 6274,
            },
            "production": {
                "mcp": 3001,
                "mcp_https": 3443,
                "chroma": 8001,
                "postgres": 5432,
                "pgadmin": 5050,
                "inspector": 6274,
            },
            "staging": {
                "mcp": 3101,
                "mcp_https": 3543,
                "chroma": 8101,
                "postgres": 5532,
                "pgadmin": 5150,
                "inspector": 6374,
            },
            "test": {
                "mcp": 3201,
                "mcp_https": 3643,
                "chroma": 8201,
                "postgres": 5632,
                "pgadmin": 5250,
                "inspector": 6474,
            },
        }

        # Get port config for environment, default to test
        ports = port_configs.get(env_name, port_configs["test"])

        # Allow individual port overrides from environment
        mcp_port = int(os.getenv("MCP_PORT", str(ports["mcp"])))
        mcp_https_port = int(os.getenv("MCP_HTTPS_PORT", str(ports["mcp_https"])))
        chroma_port = int(os.getenv("CHROMA_PORT_EXTERNAL", str(ports["chroma"])))
        postgres_port = int(os.getenv("POSTGRES_PORT_EXTERNAL", str(ports["postgres"])))
        pgadmin_port = int(os.getenv("PGADMIN_PORT", str(ports["pgadmin"])))
        inspector_port = int(os.getenv("MCP_INSPECTOR_PORT", str(ports["inspector"])))

        # Build URLs
        host = os.getenv("TEST_HOST", "localhost")
        mcp_url = os.getenv("MCP_URL", f"http://{host}:{mcp_port}/mcp/")
        inspector_url = os.getenv("MCP_INSPECTOR_URL", f"http://{host}:{inspector_port}/")
        chroma_url = os.getenv("CHROMA_URL", f"http://{host}:{chroma_port}")

        # Database URL
        db_user = os.getenv("POSTGRES_USER", "events")
        db_password = os.getenv("POSTGRES_PASSWORD", "events")
        db_name = os.getenv("POSTGRES_DB", f"events_{env_name}" if env_name != "prod" else "events")
        database_url = os.getenv(
            "DATABASE_URL",
            f"postgresql://{db_user}:{db_password}@{host}:{postgres_port}/{db_name}"
        )

        return cls(
            name=env_name,
            mcp_port=mcp_port,
            mcp_https_port=mcp_https_port,
            chroma_port=chroma_port,
            postgres_port=postgres_port,
            pgadmin_port=pgadmin_port,
            inspector_port=inspector_port,
            mcp_url=mcp_url,
            inspector_url=inspector_url,
            chroma_url=chroma_url,
            database_url=database_url,
        )

    def __str__(self) -> str:
        """Return a readable string representation."""
        return (
            f"EnvironmentConfig(name={self.name}, "
            f"mcp_port={self.mcp_port}, "
            f"chroma_port={self.chroma_port}, "
            f"postgres_port={self.postgres_port})"
        )


# ============================================================================
# Environment Configuration Fixture
# ============================================================================

@pytest.fixture(scope="session")
def env_config() -> EnvironmentConfig:
    """
    Provide environment configuration to tests.

    Session-scoped to ensure consistent configuration across all tests.

    Returns:
        EnvironmentConfig instance for the current test environment

    Example:
        def test_something(env_config):
            client = SomeClient(url=env_config.mcp_url)
    """
    return EnvironmentConfig.from_env()


# ============================================================================
# Production Safety Check
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def prevent_prod_testing(env_config: EnvironmentConfig):
    """
    Prevent tests from accidentally running against production.

    This is an autouse fixture that runs at session start.
    It will abort the test session if:
    - TEST_ENVIRONMENT is 'prod' or 'production'
    - ALLOW_PROD_TESTING is not set to 'true'

    To explicitly run tests against production (dangerous!):
        ALLOW_PROD_TESTING=true TEST_ENVIRONMENT=prod pytest ...
    """
    if env_config.name in ("prod", "production"):
        allow_prod = os.getenv("ALLOW_PROD_TESTING", "").lower() == "true"

        if not allow_prod:
            pytest.exit(
                "\n"
                "=" * 70 + "\n"
                "ERROR: Tests cannot run against PRODUCTION environment!\n"
                "=" * 70 + "\n"
                "\n"
                "This safety check prevents accidental test execution against\n"
                "production systems, which could corrupt data or cause outages.\n"
                "\n"
                "If you really need to run tests against production:\n"
                "  ALLOW_PROD_TESTING=true TEST_ENVIRONMENT=prod pytest ...\n"
                "\n"
                "WARNING: This is dangerous and should only be done for\n"
                "read-only smoke tests in controlled circumstances.\n"
                "=" * 70 + "\n",
                returncode=1
            )
        else:
            # Warn but allow
            print("\n" + "!" * 70)
            print("WARNING: Running tests against PRODUCTION environment!")
            print("ALLOW_PROD_TESTING=true was explicitly set.")
            print("Proceed with extreme caution!")
            print("!" * 70 + "\n")


# ============================================================================
# MCP Client Fixture
# ============================================================================

@pytest.fixture(scope="session")
def mcp_client(env_config: EnvironmentConfig):
    """
    Create MCP client for the configured environment.

    Session-scoped to reuse connections across tests.
    The client is initialized on first use.

    Returns:
        MCPClient instance connected to the test environment

    Example:
        def test_memory_store(mcp_client):
            response = mcp_client.call_tool("memory_store", {
                "content": "Test memory",
                "type": "preference"
            })
            assert response.success
    """
    try:
        from mcp_client import MCPClient
    except ImportError:
        # Fallback: try from lib directory
        try:
            from lib.mcp_client import MCPClient
        except ImportError:
            pytest.skip(
                "MCPClient not found. Please ensure lib/mcp_client.py exists "
                "or install the mcp_client module."
            )

    client = MCPClient(base_url=env_config.mcp_url)

    yield client

    # Cleanup
    client.close()


# ============================================================================
# Async Event Loop Fixture
# ============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """
    Create an event loop for async tests.

    Session-scoped to share the loop across all async tests.
    Required by pytest-asyncio.
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# Playwright Browser Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def browser_type_launch_args() -> dict:
    """
    Arguments for browser launch configuration.

    Environment variables:
    - HEADED: Set to 'true' for headed mode (shows browser window)
    - SLOW_MO: Milliseconds to slow down operations (for debugging)

    Returns:
        Dictionary of browser launch arguments
    """
    return {
        "headless": not os.getenv("HEADED", "").lower() == "true",
        "slow_mo": int(os.getenv("SLOW_MO", "0")),
    }


@pytest.fixture(scope="session")
def browser_context_args() -> dict:
    """
    Arguments for browser context configuration.

    Returns:
        Dictionary of browser context arguments
    """
    return {
        "viewport": {"width": 1920, "height": 1080},
        "ignore_https_errors": True,
        # Enable video recording in CI for debugging failures
        "record_video_dir": os.getenv("VIDEO_DIR") if os.getenv("CI") else None,
    }


@pytest.fixture(scope="session")
def playwright() -> Generator[Playwright, None, None]:
    """
    Session-scoped Playwright instance.

    Creates a single Playwright instance shared across all tests
    in the session for efficiency.

    Yields:
        Playwright instance
    """
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(
    playwright: Playwright,
    browser_type_launch_args: dict
) -> Generator[Browser, None, None]:
    """
    Session-scoped browser instance.

    Uses Chromium by default. The browser is shared across all tests
    in the session.

    Args:
        playwright: Playwright instance
        browser_type_launch_args: Browser launch arguments

    Yields:
        Browser instance
    """
    browser = playwright.chromium.launch(**browser_type_launch_args)
    yield browser
    browser.close()


@pytest.fixture(scope="function")
def context(
    browser: Browser,
    browser_context_args: dict
) -> Generator[BrowserContext, None, None]:
    """
    Function-scoped browser context (isolated per test).

    Each test gets a fresh browser context with:
    - Clean cookies and local storage
    - Tracing enabled for failure debugging

    Args:
        browser: Browser instance
        browser_context_args: Context arguments

    Yields:
        BrowserContext instance
    """
    context = browser.new_context(**browser_context_args)

    # Enable tracing for failure debugging
    context.tracing.start(screenshots=True, snapshots=True)

    yield context

    # Stop tracing (trace is saved on failure via hook)
    try:
        context.tracing.stop()
    except Exception:
        pass  # Ignore errors during cleanup

    context.close()


@pytest.fixture(scope="function")
def page(context: BrowserContext, env_config: EnvironmentConfig) -> Generator[Page, None, None]:
    """
    Function-scoped page (isolated per test).

    Each test gets a fresh page with:
    - Default timeout configured
    - Access to environment configuration

    Args:
        context: BrowserContext instance
        env_config: Environment configuration

    Yields:
        Page instance
    """
    page = context.new_page()

    # Set default timeout from environment or default to 30 seconds
    default_timeout = int(os.getenv("DEFAULT_TIMEOUT", "30000"))
    page.set_default_timeout(default_timeout)

    yield page

    page.close()


# ============================================================================
# Test Configuration Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def test_config() -> Dict[str, Any]:
    """
    Provide test configuration settings.

    Returns:
        Dictionary of test configuration values
    """
    return {
        # Timeouts (milliseconds)
        "default_timeout": int(os.getenv("DEFAULT_TIMEOUT", "30000")),
        "connection_timeout": int(os.getenv("CONNECTION_TIMEOUT", "15000")),
        "extraction_timeout": int(os.getenv("EXTRACTION_TIMEOUT", "120000")),
        "tool_execution_timeout": int(os.getenv("TOOL_EXECUTION_TIMEOUT", "30000")),

        # Behavior
        "cleanup_after_tests": os.getenv("CLEANUP_AFTER_TESTS", "true").lower() == "true",
        "screenshot_on_failure": os.getenv("SCREENSHOT_ON_FAILURE", "true").lower() == "true",

        # Reporting
        "report_dir": os.getenv("REPORT_DIR", "./reports"),
        "screenshot_dir": os.getenv("SCREENSHOT_DIR", "./reports/screenshots"),
        "trace_dir": os.getenv("TRACE_DIR", "./reports/traces"),

        # CI detection
        "is_ci": os.getenv("CI", "false").lower() == "true",
        "github_actions": os.getenv("GITHUB_ACTIONS", "false").lower() == "true",

        # AI Assessment
        "ai_assessment_enabled": os.getenv("AI_ASSESSMENT_ENABLED", "false").lower() == "true",
    }


@pytest.fixture(scope="session")
def mcp_inspector_token() -> Optional[str]:
    """
    Provide MCP Inspector authentication token if configured.

    Returns:
        Token string or None if not configured
    """
    return os.getenv("MCP_PROXY_AUTH_TOKEN")


# ============================================================================
# Screenshot and Trace Capture on Failure
# ============================================================================

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Save screenshot and trace on test failure.

    This hook runs after each test phase (setup, call, teardown).
    On failure during the 'call' phase, it:
    - Captures a screenshot if 'page' fixture is available
    - Saves the Playwright trace if 'context' fixture is available
    """
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        # Check if screenshot capture is enabled
        screenshot_on_failure = os.getenv("SCREENSHOT_ON_FAILURE", "true").lower() == "true"

        # Get fixtures if available
        page = item.funcargs.get("page")
        context = item.funcargs.get("context")

        # Capture screenshot
        if page and screenshot_on_failure:
            screenshot_dir = os.getenv("SCREENSHOT_DIR", "./reports/screenshots")
            os.makedirs(screenshot_dir, exist_ok=True)

            screenshot_path = os.path.join(
                screenshot_dir,
                f"{item.name}_failure.png"
            )
            try:
                page.screenshot(path=screenshot_path)
                print(f"\nScreenshot saved: {screenshot_path}")
            except Exception as e:
                print(f"\nFailed to capture screenshot: {e}")

        # Save trace
        if context:
            trace_dir = os.getenv("TRACE_DIR", "./reports/traces")
            os.makedirs(trace_dir, exist_ok=True)

            trace_path = os.path.join(trace_dir, f"{item.name}_trace.zip")
            try:
                context.tracing.stop(path=trace_path)
                print(f"Trace saved: {trace_path}")
            except Exception as e:
                print(f"\nFailed to save trace: {e}")


# ============================================================================
# Pytest Hooks
# ============================================================================

def pytest_configure(config):
    """
    Configure pytest at session start.

    This hook:
    1. Registers custom markers
    2. Prints environment information
    """
    # Register custom markers
    config.addinivalue_line(
        "markers", "api: API E2E tests (no browser required)"
    )
    config.addinivalue_line(
        "markers", "artifact: Artifact-related tests"
    )
    config.addinivalue_line(
        "markers", "health: Health check and connectivity tests"
    )
    config.addinivalue_line(
        "markers", "memory: Memory-related tests"
    )
    config.addinivalue_line(
        "markers", "event: Event-related tests"
    )
    config.addinivalue_line(
        "markers", "smoke: Smoke tests that should run first"
    )
    config.addinivalue_line(
        "markers", "browser: Browser UI tests (MCP Inspector)"
    )
    config.addinivalue_line(
        "markers", "integration: Cross-service integration tests"
    )
    config.addinivalue_line(
        "markers", "quality: AI-assessed quality tests"
    )
    config.addinivalue_line(
        "markers", "performance: Performance benchmark tests"
    )
    config.addinivalue_line(
        "markers", "v3: V3-specific tests (event extraction)"
    )
    config.addinivalue_line(
        "markers", "v4: V4-specific tests (entity resolution, graph)"
    )
    config.addinivalue_line(
        "markers", "slow: Slow running tests (>30s)"
    )
    config.addinivalue_line(
        "markers", "requires_postgres: Tests requiring Postgres database"
    )
    config.addinivalue_line(
        "markers", "requires_worker: Tests requiring event extraction worker"
    )
    config.addinivalue_line(
        "markers", "requires_ai: Tests requiring OpenAI API (costs money)"
    )
    config.addinivalue_line(
        "markers", "skip_ci: Skip in CI environment"
    )
    config.addinivalue_line(
        "markers", "wip: Work in progress (skip by default)"
    )

    # Print environment info at session start
    env_config = EnvironmentConfig.from_env()

    print("\n" + "=" * 70)
    print("MCP Memory Server Test Suite")
    print("=" * 70)
    print(f"Environment:     {env_config.name.upper()}")
    print(f"MCP Server:      {env_config.mcp_url}")
    print(f"MCP Inspector:   {env_config.inspector_url}")
    print(f"ChromaDB:        {env_config.chroma_url}")
    print(f"PostgreSQL:      localhost:{env_config.postgres_port}")
    print("=" * 70 + "\n")


# ============================================================================
# Skip CI Tests When Not in CI
# ============================================================================

def pytest_collection_modifyitems(config, items):
    """
    Modify test collection based on environment.

    - Skip tests marked with 'skip_ci' when running in CI
    - Skip tests marked with 'wip' unless explicitly requested
    - Skip tests marked with 'requires_ai' if AI assessment is disabled
    """
    is_ci = os.getenv("CI", "false").lower() == "true"
    ai_enabled = os.getenv("AI_ASSESSMENT_ENABLED", "false").lower() == "true"
    run_wip = os.getenv("RUN_WIP_TESTS", "false").lower() == "true"

    skip_ci = pytest.mark.skip(reason="Skipped in CI environment")
    skip_wip = pytest.mark.skip(reason="Work in progress - set RUN_WIP_TESTS=true to run")
    skip_ai = pytest.mark.skip(reason="Requires AI - set AI_ASSESSMENT_ENABLED=true to run")

    for item in items:
        # Skip tests marked with skip_ci when in CI
        if is_ci and "skip_ci" in item.keywords:
            item.add_marker(skip_ci)

        # Skip WIP tests unless explicitly enabled
        if "wip" in item.keywords and not run_wip:
            item.add_marker(skip_wip)

        # Skip AI tests unless enabled
        if "requires_ai" in item.keywords and not ai_enabled:
            item.add_marker(skip_ai)
