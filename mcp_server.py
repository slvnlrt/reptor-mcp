# mcp_server.py
"""
reptor-mcp: MCP Server exposing reptor CLI plugins for SysReptor automation.

Creates and configures the FastMCP application.  The server dynamically
generates MCP tools from all reptor CLI plugins and registers custom
direct-API tools for common operations (findings CRUD, schema, templates).

Usage:
    fastmcp run mcp_server.py:mcp --transport streamable-http --port 8008
"""
import io
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.utilities.logging import get_logger
from reptor.lib.reptor import Reptor

from custom_tools import FieldExcluder, register_custom_tools
from tool_generator import ToolGenerator

logger = get_logger("reptor-mcp")

# --- Optional: dev-mode path for local reptor source ---
_reptor_dev_path = os.environ.get("REPTOR_MAIN_PATH")
if _reptor_dev_path and os.path.isdir(_reptor_dev_path):
    sys.path.insert(0, _reptor_dev_path)
    logger.info(f"Dev mode: added {_reptor_dev_path} to sys.path")

_initialized = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_reptor_instance() -> Reptor:
    """Create a Reptor instance with suppressed startup output."""
    saved = sys.stdout, sys.stderr, sys.stdin
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    sys.stdin = io.TextIOWrapper(io.BytesIO(b""), encoding="utf-8")
    try:
        return Reptor()
    finally:
        sys.stdout, sys.stderr, sys.stdin = saved


def _configure_ssl(config) -> None:
    """Apply SSL/TLS settings from environment variables."""
    if os.environ.get("REPTOR_MCP_INSECURE", "false").lower() == "true":
        config.set("insecure", True)
    else:
        ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE")
        if ca_bundle:
            config.set("requests_ca_bundle", ca_bundle)
        config.set("insecure", False)


def _create_field_excluder() -> FieldExcluder | None:
    """Create a FieldExcluder from REPTOR_MCP_EXCLUDE_FIELDS env var."""
    raw = os.environ.get("REPTOR_MCP_EXCLUDE_FIELDS", "")
    fields = [f.strip() for f in raw.split(",") if f.strip()]
    if fields:
        logger.info(f"Field exclusion enabled for: {fields}")
        return FieldExcluder(fields)
    return None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastMCP):
    global _initialized
    if not _initialized:
        if os.environ.get("REPTOR_MCP_DEBUG", "false").lower() == "true":
            logger.setLevel(logging.DEBUG)

        logger.info("Initializing reptor-mcp server...")

        reptor = _create_reptor_instance()
        _configure_ssl(reptor.get_config())

        reptor.plugin_manager.run_loading_sequence()
        reptor.plugin_manager.load_plugins()

        field_excluder = _create_field_excluder()

        # Dynamic wrappers for all CLI plugins
        generator = ToolGenerator(mcp_server=app, reptor_instance=reptor)
        generator.generate_tools()

        # Custom tools using direct reptor API
        register_custom_tools(app, reptor, field_excluder)

        _initialized = True
        logger.info("Server ready.")

    yield
    _initialized = False
    logger.info("Server shutting down.")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="reptor-mcp",
    instructions=(
        "MCP server for SysReptor pentest reporting. Exposes reptor CLI plugins "
        "as tools (nmap, nessus, burp, zap, sslyze, etc.) and provides direct "
        "API tools for findings CRUD, schema discovery, and template management."
    ),
    lifespan=lifespan,
)
