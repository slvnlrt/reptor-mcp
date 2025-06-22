# mcp_server.py
import io
import sys
import logging
import os
from contextlib import asynccontextmanager

# --- Dynamic Path Loading for Reptor ---
REPTOR_PATH = os.environ.get("REPTOR_MAIN_PATH")
if REPTOR_PATH and os.path.isdir(REPTOR_PATH):
    sys.path.insert(0, REPTOR_PATH)
    print(f"INFO: Added {REPTOR_PATH} to sys.path for Reptor library.")
# --- End Dynamic Path Loading ---

from fastmcp import FastMCP
from reptor.lib.reptor import Reptor
from fastmcp.utilities.logging import get_logger

from tool_generator import ToolGenerator

script_logger = get_logger("reptor-mcp.mcp_server")
script_logger.setLevel(logging.INFO)

reptor_instance = None
_server_initialized = False

async def initialize_server_logic(app: FastMCP):
    global reptor_instance, _server_initialized
    
    if _server_initialized:
        script_logger.info("Server initialization already performed. Skipping lifespan startup logic.")
        return

    _server_initialized = True
    script_logger.info("Lifespan startup: Running one-time server initialization logic (first time)...")

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    original_stdin = sys.stdin
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    sys.stdin = io.TextIOWrapper(io.BytesIO(b''), encoding='utf-8')

    try:
        reptor_instance = Reptor()
    finally:
        sys.stdout = original_stdout
        captured_stderr_content = ""
        if isinstance(sys.stderr, io.StringIO):
            captured_stderr_content = sys.stderr.getvalue()
        sys.stderr = original_stderr
        sys.stdin = original_stdin
        if captured_stderr_content and os.environ.get('REPTOR_MCP_DEBUG', 'false').lower() == 'true':
            script_logger.debug("--- Captured Stderr During Shielded Block ---")
            script_logger.debug(captured_stderr_content.strip())
            script_logger.debug("--- End Captured Stderr ---")

    if reptor_instance is None:
        raise RuntimeError("Reptor instance could not be initialized.")

    config = reptor_instance.get_config()
    if os.environ.get('REPTOR_MCP_INSECURE', 'false').lower() == 'true':
        config.set("insecure", True)
    else:
        ca_bundle_path = os.environ.get('REQUESTS_CA_BUNDLE')
        if ca_bundle_path:
            config.set("requests_ca_bundle", ca_bundle_path)
            config.set("insecure", False) 
        else:
            config.set("insecure", False)

    reptor_instance.plugin_manager.run_loading_sequence()
    reptor_instance.plugin_manager.load_plugins()

    generator = ToolGenerator(mcp_server=app, reptor_instance=reptor_instance)
    generator.generate_tools()
    script_logger.info("Lifespan startup: One-time server initialization logic complete.")

    if os.environ.get('REPTOR_MCP_DEBUG', 'false').lower() == 'true':
        script_logger.setLevel(logging.DEBUG)

@asynccontextmanager
async def lifespan_manager(app: FastMCP):
    script_logger.info(f"Lifespan: Startup sequence initiated for app: {app.name}")
    await initialize_server_logic(app)
    yield
    script_logger.info(f"Lifespan: Shutdown sequence initiated for app: {app.name}")

def create_app() -> FastMCP:
    script_logger.info("Creating FastMCP application instance...")
    
    mcp_app = FastMCP(
        name="reptor-mcp",
        instructions="An MCP server to interact with the Reptor CLI.",
        lifespan=lifespan_manager
    )
    script_logger.info(f"FastMCP application instance '{mcp_app.name}' created.")
    return mcp_app

# Create the application instance using the factory.
# This 'mcp' object is what 'fastmcp run mcp_server.py:mcp' will discover and run.
mcp = create_app()