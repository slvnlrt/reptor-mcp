# wrapper_utils.py
# Utility functions to help construct and manage
# the execution logic within the dynamically generated MCP tool wrappers.

import io
import sys
import inspect # For signature access if needed by helpers
import logging
import keyword # For checking param names
from contextlib import redirect_stdout, AbstractContextManager # For type hint
from typing import Any, TYPE_CHECKING

from fastmcp.server.context import Context
from rich.table import Table as RichTable
from rich.console import Console as RichConsole

# Import configurations from tool_config.py
from tool_config import STDIN_CONSUMING_PLUGINS, CONFIG_OVERWRITE_PARAMS, PLUGINS_REQUIRING_CONFIG_POPULATION


if TYPE_CHECKING:
    from reptor.lib.reptor import Reptor # For type hinting reptor_instance or its config
    from reptor.lib.conf import Config as ReptorConfig # For reptor_instance_config

from fastmcp.utilities.logging import get_logger
script_logger = get_logger("reptor-mcp.wrapper_utils") # Standard logger for utilities
# script_logger.setLevel(logging.DEBUG) # Uncomment for detailed debug logs from this module


def prepare_cli_args_for_plugin(signature: inspect.Signature, mcp_kwargs: dict) -> dict:
    """
    Prepares the cli_args dictionary from the MCP kwargs and signature defaults.
    """
    cli_args = {}
    for p_name, p_obj in signature.parameters.items():
        if p_name == 'ctx':
            continue
        
        # Map potentially suffixed MCP param name back to original argparse dest
        original_dest_name = p_name[:-1] if p_name.endswith('_') and keyword.iskeyword(p_name[:-1]) else p_name

        if p_name in mcp_kwargs: # Value from MCP call takes precedence
            cli_args[original_dest_name] = mcp_kwargs[p_name]
        elif p_obj.default is not inspect.Parameter.empty: # Otherwise, use default from signature
            cli_args[original_dest_name] = p_obj.default
    return cli_args

class StdinRedirector(AbstractContextManager):
    def __init__(self, new_stdin_content: str | None):
        self.new_stdin_content = new_stdin_content
        self.original_stdin = None

    def __enter__(self):
        if self.new_stdin_content is not None:
            self.original_stdin = sys.stdin
            sys.stdin = io.StringIO(self.new_stdin_content)
            script_logger.debug("Redirected sys.stdin with new content.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.original_stdin is not None:
            sys.stdin = self.original_stdin
            script_logger.debug("Restored original sys.stdin.")
        # Do not suppress exceptions
        return False

def handle_stdin_redirection_and_args(
    plugin_name: str, 
    cli_args: dict, 
    mcp_kwargs: dict
) -> tuple[AbstractContextManager, dict]:
    """
    Handles stdin redirection if needed and removes _stdin_content from cli_args.
    Returns a context manager for stdin and the modified cli_args.
    """
    stdin_content_to_redirect = None
    if plugin_name in STDIN_CONSUMING_PLUGINS and "_stdin_content" in mcp_kwargs and mcp_kwargs["_stdin_content"] is not None:
        stdin_content_to_redirect = mcp_kwargs["_stdin_content"]
        if "_stdin_content" in cli_args: # Should be there if it was in mcp_kwargs
            del cli_args["_stdin_content"]
            script_logger.debug(f"Removed _stdin_content from cli_args for {plugin_name}")

    return StdinRedirector(stdin_content_to_redirect), cli_args


def apply_cli_config_overwrites(
    reptor_instance_config: "ReptorConfig", 
    plugin_name: str, 
    mcp_kwargs: dict,
    cli_args: dict # cli_args is modified in place if synth_param is removed
) -> None:
    """
    Applies CLI configuration overwrites based on synthetic parameters.
    Modifies cli_args by removing processed synthetic parameters.
    """
    if plugin_name in CONFIG_OVERWRITE_PARAMS:
        cli_overwrites = reptor_instance_config.get_cli_overwrite() # Get the dictionary
        modified_overwrites = False
        for synth_param_name, synth_param_details in CONFIG_OVERWRITE_PARAMS[plugin_name].items():
            if synth_param_name in mcp_kwargs and mcp_kwargs[synth_param_name] is not None:
                config_key = synth_param_details["config_key"]
                cli_overwrites[config_key] = mcp_kwargs[synth_param_name]
                modified_overwrites = True
                if synth_param_name in cli_args: # Remove from direct plugin args
                    del cli_args[synth_param_name]
                    script_logger.debug(f"Removed synthetic param {synth_param_name} from cli_args for {plugin_name}")
        if modified_overwrites:
            reptor_instance_config.set("cli", cli_overwrites) # Set the modified dictionary back
            script_logger.debug(f"Applied CLI config overwrites for {plugin_name}: {cli_overwrites}")


def populate_config_for_special_plugins(
    reptor_instance_config: "ReptorConfig", 
    plugin_name: str, 
    cli_args: dict, 
    ctx: Context
) -> bool:
    """
    Populates config for plugins in PLUGINS_REQUIRING_CONFIG_POPULATION.
    Returns True if special population was done, False otherwise.
    """
    if plugin_name in PLUGINS_REQUIRING_CONFIG_POPULATION:
        current_cli_config = reptor_instance_config.get_cli_overwrite().copy()
        processed_cli_args_for_config = {}

        for arg_name, arg_value in cli_args.items():
            if plugin_name == "file" and arg_name == "file" and isinstance(arg_value, list):
                opened_files = []
                for filepath_str in arg_value:
                    try:
                        # Assuming 'r' mode is default; adjust if other modes are needed
                        opened_files.append(open(filepath_str, 'r')) 
                        script_logger.debug(f"Opened file {filepath_str} for {plugin_name}")
                    except Exception as e_open:
                        ctx.error(f"Error opening file {filepath_str} for tool {plugin_name}: {e_open}")
                        # opened_files.append(None) # Or raise, or skip
                # Only pass successfully opened files
                processed_cli_args_for_config[arg_name] = [f for f in opened_files if f is not None]
                if not processed_cli_args_for_config[arg_name] and arg_value: # If paths were given but none opened
                    ctx.warning(f"No valid files to process for tool {plugin_name} for arg '{arg_name}'. Input paths: {arg_value}")
            else:
                processed_cli_args_for_config[arg_name] = arg_value
        
        for cfg_arg_name, cfg_arg_value in processed_cli_args_for_config.items():
            current_cli_config[cfg_arg_name] = cfg_arg_value
        
        reptor_instance_config.set("cli", current_cli_config)
        ctx.debug(f"Updated cli_config for special plugin '{plugin_name}': {current_cli_config}")
        script_logger.debug(f"Updated cli_config for special plugin '{plugin_name}': {current_cli_config}")
        return True
    return False

def adjust_project_tool_args(plugin_name: str, cli_args: dict, mcp_kwargs: dict, signature: inspect.Signature, ctx: Context) -> None:
    """
    Special handling for 'project' tool to ensure search works when 'finish' defaults.
    Modifies cli_args in place.
    """
    if plugin_name == "project":
        sig_finish_param = signature.parameters.get('finish')
        sig_finish_default = sig_finish_param.default if sig_finish_param else inspect.Parameter.empty
        
        finish_explicitly_passed_in_kwargs = 'finish' in mcp_kwargs
        current_finish_value_in_cli_args = cli_args.get('finish')

        log_msg_prefix = f"wrapper_utils: '{plugin_name}', Project Specific Handling:"
        ctx.debug(log_msg_prefix)
        script_logger.debug(log_msg_prefix)
        
        debug_details = [
            f"  Signature 'finish' default: {sig_finish_default}",
            f"  'finish' explicitly passed in MCP call (mcp_kwargs): {finish_explicitly_passed_in_kwargs}",
            f"  Current 'finish' value in cli_args: {current_finish_value_in_cli_args}"
        ]
        for detail in debug_details: ctx.debug(detail); script_logger.debug(detail)

        no_other_major_action = not cli_args.get('export') and \
                                not cli_args.get('render') and \
                                not cli_args.get('duplicate')
        ctx.debug(f"  No other major action (export/render/duplicate): {no_other_major_action}")
        script_logger.debug(f"  No other major action (export/render/duplicate): {no_other_major_action}")
        
        if not finish_explicitly_passed_in_kwargs and \
           current_finish_value_in_cli_args is False and \
           no_other_major_action:
            ctx.info(f"'{plugin_name}': 'finish' defaulted to False, no other action. Overriding to None for search.")
            script_logger.info(f"'{plugin_name}': 'finish' defaulted to False, no other action. Overriding to None for search.")
            cli_args['finish'] = None
        else:
            ctx.debug(f"'{plugin_name}': Not overriding 'finish'. Final 'finish' in cli_args: {cli_args.get('finish')}")
            script_logger.debug(f"'{plugin_name}': Not overriding 'finish'. Final 'finish' in cli_args: {cli_args.get('finish')}")


class CapturingStdOut:
    def __init__(self):
        self._string_io = io.StringIO()
        self._bytes_io = io.BytesIO()
        self._buffer_used = False

    def write(self, data: str):
        # This method is for text writes (like print())
        return self._string_io.write(data)

    @property
    def buffer(self):
        # This property allows access to a binary buffer (like sys.stdout.buffer)
        self._buffer_used = True
        return self._bytes_io

    def flush(self):
        self._string_io.flush()
        self._bytes_io.flush()

    def getvalue(self):
        if self._buffer_used and self._bytes_io.tell() > 0:
            # If buffer was used and has content, prioritize it.
            # Attempt to decode as UTF-8, fallback to repr for safety.
            try:
                return self._bytes_io.getvalue().decode('utf-8').strip()
            except UnicodeDecodeError:
                script_logger.warning("Could not decode captured stdout buffer as UTF-8. Returning raw bytes representation.")
                return repr(self._bytes_io.getvalue()).strip()
        return self._string_io.getvalue().strip()

    def isatty(self): # Some libraries check this
        return False

    @property
    def encoding(self): # Some libraries check this
        return 'utf-8'


def execute_plugin_and_capture_output(plugin_instance: Any, plugin_name: str, ctx: Context) -> str:
    """
    Executes the plugin's run method and captures its stdout.
    Includes redirection for instance.print and instance.console.print.
    Uses CapturingStdOut to handle both text and binary stdout.
    """
    output_capture_stream = CapturingStdOut()
    original_instance_print = None
    original_console_print = None
    
    try:
        # General redirection for instance.print
        if hasattr(plugin_instance, "print") and callable(plugin_instance.print):
            script_logger.debug(f"Redirecting 'instance.print' for plugin '{plugin_name}' to sys.stdout.")
            original_instance_print = plugin_instance.print
            def redirected_instance_print_to_stdout(*p_args, **p_kwargs):
                print(*p_args, file=sys.stdout, **p_kwargs) # Explicitly to current sys.stdout
            plugin_instance.print = redirected_instance_print_to_stdout

        # General redirection for instance.console.print
        if hasattr(plugin_instance, "console") and hasattr(plugin_instance.console, "print") and callable(plugin_instance.console.print):
            script_logger.debug(f"Redirecting 'instance.console.print' for plugin '{plugin_name}' to sys.stdout.")
            original_console_print = plugin_instance.console.print
            def redirected_console_print_to_stdout(*p_args, **p_kwargs):
                if p_args and isinstance(p_args[0], RichTable):
                    table_to_print = p_args[0]
                    # Use a temporary StringIO for Rich rendering to text
                    temp_capture_buffer = io.StringIO()
                    temp_rich_console = RichConsole(file=temp_capture_buffer, force_terminal=True, legacy_windows=False, width=120)
                    temp_rich_console.print(table_to_print)
                    # Then print this text to the main (potentially CapturingStdOut) sys.stdout
                    print(temp_capture_buffer.getvalue(), file=sys.stdout, **p_kwargs)
                else:
                    print(*p_args, file=sys.stdout, **p_kwargs) # Explicitly to current sys.stdout
            plugin_instance.console.print = redirected_console_print_to_stdout
        
        with redirect_stdout(output_capture_stream): # Use the new CapturingStdOut instance
            ctx.info(f"PRE-instance.run() for '{plugin_name}'...")
            script_logger.info(f"PRE-instance.run() for '{plugin_name}'...")
            plugin_instance.run()
            ctx.info(f"POST-instance.run() for '{plugin_name}'.")
            script_logger.info(f"POST-instance.run() for '{plugin_name}'.")

    except ValueError as ve:
        error_message = f"Configuration error for tool '{plugin_name}': {ve}. Ensure REPTOR_SERVER/TOKEN are set or config.yaml is correct."
        ctx.error(error_message)
        script_logger.error(f"CONFIG ERROR running plugin {plugin_name}: {ve}", exc_info=False)
        return error_message
    except Exception as e:
        ctx.error(f"Error running plugin '{plugin_name}': {type(e).__name__} - {e}")
        script_logger.error(f"ERROR running plugin {plugin_name}: {e}", exc_info=True)
        return f"Error executing tool {plugin_name}: {type(e).__name__} - {str(e)}"
    finally:
        # Ensure restoration of original methods
        if original_instance_print and hasattr(plugin_instance, "print"): # Check hasattr in case instance was None
            plugin_instance.print = original_instance_print
            script_logger.debug(f"Restored 'instance.print' for plugin '{plugin_name}'.")
        if original_console_print and hasattr(plugin_instance, "console"): # Check hasattr
            plugin_instance.console.print = original_console_print
            script_logger.debug(f"Restored 'instance.console.print' for plugin '{plugin_name}'.")
            
    result = output_capture_stream.getvalue() # Get value from the new class
    ctx.info(f"Tool '{plugin_name}' completed. Output: {result[:200]}...")
    return result