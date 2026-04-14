# wrapper_utils.py
"""
Utility functions for the dynamically generated MCP tool wrappers.

Handles CLI argument preparation, stdin redirection, config overwrites,
plugin instantiation helpers, and output capture.
"""
import io
import sys
import inspect
import keyword
from contextlib import redirect_stdout, AbstractContextManager
from typing import Any, TYPE_CHECKING

from fastmcp.utilities.logging import get_logger
from rich.table import Table as RichTable
from rich.console import Console as RichConsole

from tool_config import STDIN_CONSUMING_PLUGINS, CONFIG_OVERWRITE_PARAMS, PLUGINS_REQUIRING_CONFIG_POPULATION

if TYPE_CHECKING:
    from reptor.lib.conf import Config as ReptorConfig

logger = get_logger("reptor-mcp.wrapper_utils")


# ---------------------------------------------------------------------------
# CLI argument preparation
# ---------------------------------------------------------------------------

def prepare_cli_args_for_plugin(signature: inspect.Signature, mcp_kwargs: dict) -> dict:
    """Build the cli_args dict from MCP kwargs merged with signature defaults."""
    cli_args = {}
    for p_name, p_obj in signature.parameters.items():
        if p_name == "ctx":
            continue
        # Map suffixed param name back to original argparse dest (e.g. from_ -> from)
        original_dest = p_name[:-1] if p_name.endswith("_") and keyword.iskeyword(p_name[:-1]) else p_name

        if p_name in mcp_kwargs:
            cli_args[original_dest] = mcp_kwargs[p_name]
        elif p_obj.default is not inspect.Parameter.empty:
            # Copy mutable defaults to avoid cross-call contamination
            default = p_obj.default
            cli_args[original_dest] = list(default) if isinstance(default, list) else default
    return cli_args


# ---------------------------------------------------------------------------
# Stdin redirection
# ---------------------------------------------------------------------------

class StdinRedirector(AbstractContextManager):
    """Context manager that temporarily replaces sys.stdin with string content."""

    def __init__(self, content: str | None):
        self._content = content
        self._original_stdin = None

    def __enter__(self):
        if self._content is not None:
            self._original_stdin = sys.stdin
            sys.stdin = io.StringIO(self._content)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._original_stdin is not None:
            sys.stdin = self._original_stdin
        return False


def handle_stdin_redirection_and_args(
    plugin_name: str,
    cli_args: dict,
    mcp_kwargs: dict,
) -> tuple[AbstractContextManager, dict]:
    """Extract _stdin_content from kwargs and return a stdin context manager."""
    stdin_content = None
    if plugin_name in STDIN_CONSUMING_PLUGINS and mcp_kwargs.get("_stdin_content") is not None:
        stdin_content = mcp_kwargs["_stdin_content"]
        cli_args.pop("_stdin_content", None)
    return StdinRedirector(stdin_content), cli_args


# ---------------------------------------------------------------------------
# Config overwrites
# ---------------------------------------------------------------------------

def apply_cli_config_overwrites(
    config: "ReptorConfig",
    plugin_name: str,
    mcp_kwargs: dict,
    cli_args: dict,
) -> None:
    """Apply synthetic MCP parameters as reptor CLI config overwrites."""
    if plugin_name not in CONFIG_OVERWRITE_PARAMS:
        return
    cli_overwrites = config.get_cli_overwrite()
    modified = False
    for synth_name, synth_details in CONFIG_OVERWRITE_PARAMS[plugin_name].items():
        if synth_name in mcp_kwargs and mcp_kwargs[synth_name] is not None:
            cli_overwrites[synth_details["config_key"]] = mcp_kwargs[synth_name]
            modified = True
            cli_args.pop(synth_name, None)
    if modified:
        config.set("cli", cli_overwrites)
        logger.debug(f"Applied CLI config overwrites for {plugin_name}: {cli_overwrites}")


# ---------------------------------------------------------------------------
# Special plugin config population
# ---------------------------------------------------------------------------

def populate_config_for_special_plugins(
    config: "ReptorConfig",
    plugin_name: str,
    cli_args: dict,
) -> bool:
    """Populate config for plugins that read args from config instead of kwargs.

    Returns True if special population was performed, False otherwise.
    """
    if plugin_name not in PLUGINS_REQUIRING_CONFIG_POPULATION:
        return False

    current_cli_config = config.get_cli_overwrite().copy()
    processed_args: dict[str, Any] = {}

    for arg_name, arg_value in cli_args.items():
        if plugin_name == "file" and arg_name == "file" and isinstance(arg_value, list):
            # Open file handles in binary mode (matches reptor's argparse.FileType('rb'))
            # NOTE: caller should close these in a finally block after plugin execution
            opened_files: list[Any] = []
            for filepath_str in arg_value:
                try:
                    opened_files.append(open(filepath_str, "rb"))
                except OSError as e:
                    for f in opened_files:
                        f.close()
                    opened_files = []
                    logger.error(f"Cannot open file '{filepath_str}': {e}")
                    break
            if not opened_files and arg_value:
                logger.warning(f"No files could be opened for tool '{plugin_name}'")
            processed_args[arg_name] = opened_files
        else:
            processed_args[arg_name] = arg_value

    for key, value in processed_args.items():
        current_cli_config[key] = value

    config.set("cli", current_cli_config)
    logger.debug(f"Populated cli_config for special plugin '{plugin_name}': {current_cli_config}")
    return True


# ---------------------------------------------------------------------------
# Output capture
# ---------------------------------------------------------------------------

class CapturingStdOut:
    """Captures both text and binary stdout writes."""

    def __init__(self):
        self._string_io = io.StringIO()
        self._bytes_io = io.BytesIO()
        self._buffer_used = False

    def write(self, data: str):
        return self._string_io.write(data)

    @property
    def buffer(self):
        self._buffer_used = True
        return self._bytes_io

    def flush(self):
        self._string_io.flush()
        self._bytes_io.flush()

    def getvalue(self) -> str:
        text = self._string_io.getvalue().strip()
        if self._buffer_used and self._bytes_io.tell() > 0:
            try:
                binary_text = self._bytes_io.getvalue().decode("utf-8").strip()
            except UnicodeDecodeError:
                logger.warning("Could not decode captured stdout buffer as UTF-8")
                binary_text = repr(self._bytes_io.getvalue()).strip()
            return f"{text}\n{binary_text}".strip() if text else binary_text
        return text

    def isatty(self):
        return False

    @property
    def encoding(self):
        return "utf-8"


def execute_plugin_and_capture_output(plugin_instance: Any, plugin_name: str) -> str:
    """Execute a plugin's run() method and return its captured stdout as a string."""
    capture = CapturingStdOut()
    original_instance_print = None
    original_console_print = None

    try:
        # Redirect instance.print -> sys.stdout
        if hasattr(plugin_instance, "print") and callable(plugin_instance.print):
            original_instance_print = plugin_instance.print

            def redirected_print(*args, **kwargs):
                print(*args, file=sys.stdout, **kwargs)

            plugin_instance.print = redirected_print

        # Redirect instance.console.print -> sys.stdout (with Rich table support)
        if hasattr(plugin_instance, "console") and hasattr(plugin_instance.console, "print"):
            original_console_print = plugin_instance.console.print

            def redirected_console_print(*args, **kwargs):
                if args and isinstance(args[0], RichTable):
                    buf = io.StringIO()
                    temp_console = RichConsole(file=buf, force_terminal=True, legacy_windows=False, width=120)
                    temp_console.print(args[0])
                    print(buf.getvalue(), file=sys.stdout, **kwargs)
                else:
                    print(*args, file=sys.stdout, **kwargs)

            plugin_instance.console.print = redirected_console_print

        with redirect_stdout(capture):
            plugin_instance.run()

    except ValueError as ve:
        msg = f"Configuration error for tool '{plugin_name}': {ve}"
        logger.error(msg)
        return msg
    except Exception as e:
        logger.error(f"Error running plugin {plugin_name}: {e}", exc_info=True)
        return f"Error executing tool {plugin_name}: {type(e).__name__} - {e}"
    finally:
        if original_instance_print and hasattr(plugin_instance, "print"):
            plugin_instance.print = original_instance_print
        if original_console_print and hasattr(plugin_instance, "console"):
            plugin_instance.console.print = original_console_print

    result = capture.getvalue()
    logger.debug(f"Tool '{plugin_name}' output ({len(result)} chars): {result[:200]}")
    return result
