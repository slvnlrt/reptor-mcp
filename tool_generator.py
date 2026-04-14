# tool_generator.py
"""Dynamically generates MCP tools from reptor CLI plugin argparse definitions."""
import argparse
import asyncio
import inspect
import keyword
import threading
from typing import Any, TYPE_CHECKING
from collections.abc import Callable

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from reptor.lib.reptor import Reptor

from fastmcp.server.context import Context
from fastmcp.utilities.logging import get_logger

from tool_config import (
    EXCLUDED_PLUGINS,
    STDIN_CONSUMING_PLUGINS,
    CONFIG_OVERWRITE_PARAMS,
)
from signature_utils import create_tool_signature, build_tool_docstring
from wrapper_utils import (
    prepare_cli_args_for_plugin,
    handle_stdin_redirection_and_args,
    apply_cli_config_overwrites,
    populate_config_for_special_plugins,
    execute_plugin_and_capture_output,
)

logger = get_logger("reptor-mcp.tool_generator")

# Serialize all plugin execution to avoid thread-safety issues
# with the shared Reptor instance, sys.stdin/stdout redirection, etc.
_execution_lock = threading.Lock()


class ToolGenerator:
    def __init__(self, mcp_server: "FastMCP", reptor_instance: "Reptor"):
        self.mcp = mcp_server
        self.reptor = reptor_instance

    def generate_tools(self):
        """Generate and register an MCP tool for each loaded reptor plugin."""
        registered = 0
        skipped = 0
        for name, module in self.reptor.plugin_manager.LOADED_PLUGINS.items():
            if name in EXCLUDED_PLUGINS:
                logger.debug(f"Skipping excluded plugin: {name}")
                skipped += 1
                continue
            if self._generate_tool_from_plugin(name, module):
                registered += 1
        logger.info(f"Generated {registered} plugin tools (skipped {skipped} excluded)")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _consolidate_actions(
        self, parser: argparse.ArgumentParser, plugin_name: str
    ) -> dict[str, list[argparse.Action]]:
        """Group argparse actions by their destination."""
        actions_by_dest: dict[str, list[argparse.Action]] = {}
        for action in parser._actions:
            if not isinstance(action, argparse._HelpAction):
                actions_by_dest.setdefault(action.dest, []).append(action)
        return actions_by_dest

    def _generate_tool_from_plugin(self, name: str, module: Any) -> bool:
        """Create and register a single MCP tool from a reptor plugin. Returns True on success."""
        plugin_loader_class = module.loader
        plugin_meta = plugin_loader_class.meta

        parser = argparse.ArgumentParser(prog=name, description=plugin_meta.get("summary"))
        try:
            plugin_loader_class.add_arguments(parser, plugin_filepath=module.__file__)
        except Exception as e:
            logger.error(f"Failed to add arguments for plugin {name}: {e}", exc_info=True)
            return False

        actions_by_dest = self._consolidate_actions(parser, name)

        signature = create_tool_signature(
            name, actions_by_dest, STDIN_CONSUMING_PLUGINS, CONFIG_OVERWRITE_PARAMS
        )
        if signature is None:
            logger.warning(f"Could not create signature for plugin {name}, skipping")
            return False

        tool_wrapper = self._create_tool_wrapper(name, signature, plugin_loader_class)
        tool_wrapper.__doc__ = build_tool_docstring(name, signature, plugin_meta, actions_by_dest)

        mcp_tool_name = name + "_" if keyword.iskeyword(name) else name

        try:
            self.mcp.tool(name=mcp_tool_name)(tool_wrapper)
            logger.info(f"Registered tool: {mcp_tool_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to register tool {mcp_tool_name}: {e}", exc_info=True)
            return False

    def _create_tool_wrapper(
        self, name: str, signature: inspect.Signature, plugin_loader_class: Any
    ) -> Callable:
        """Build an async wrapper function that bridges MCP calls to a reptor plugin."""

        async def tool_wrapper(ctx: Context, **kwargs):
            await ctx.info(f"Executing tool: '{name}'")

            # 1. Prepare CLI args from MCP kwargs and signature defaults
            cli_args = prepare_cli_args_for_plugin(signature, kwargs)

            # 2-7: Run the blocking plugin execution in a thread with a lock
            # to avoid blocking the event loop and to serialize access to
            # the shared Reptor instance / sys.stdin / sys.stdout.
            def _run_plugin():
                with _execution_lock:
                    # 2. Handle stdin redirection (for plugins that consume stdin)
                    stdin_manager, final_args = handle_stdin_redirection_and_args(name, cli_args, kwargs)

                    with stdin_manager:
                        # 3. Apply config overwrites from synthetic parameters
                        if not self.reptor:
                            return f"Error: Reptor instance not initialized for tool {name}."
                        apply_cli_config_overwrites(self.reptor.get_config(), name, kwargs, final_args)

                        # 4. Special adjustments (e.g. 'project' tool finish flag)
                        _adjust_project_tool_args_sync(name, final_args, kwargs, signature)

                        # 5. Instantiate the plugin
                        try:
                            was_special = populate_config_for_special_plugins(
                                self.reptor.get_config(), name, final_args
                            )
                            if was_special:
                                instance = plugin_loader_class(reptor=self.reptor)
                            else:
                                instance = plugin_loader_class(reptor=self.reptor, **final_args)
                        except Exception as e:
                            logger.error(f"Failed to instantiate plugin {name}: {e}", exc_info=True)
                            return f"Error instantiating tool {name}: {e}"

                        # 6. Execute and capture output
                        return execute_plugin_and_capture_output(instance, name)

            result = await asyncio.to_thread(_run_plugin)
            await ctx.info(f"Tool '{name}' completed")
            return result

        tool_wrapper.__signature__ = signature
        tool_wrapper.__annotations__ = {
            p.name: p.annotation
            for p in signature.parameters.values()
            if p.annotation is not inspect.Parameter.empty
        }
        return tool_wrapper


def _adjust_project_tool_args_sync(
    plugin_name: str,
    cli_args: dict,
    mcp_kwargs: dict,
    signature: inspect.Signature,
) -> None:
    """For the 'project' tool: override 'finish' default so search works. (sync version)"""
    if plugin_name != "project":
        return

    finish_explicitly_passed = "finish" in mcp_kwargs
    current_finish = cli_args.get("finish")
    no_other_action = not cli_args.get("export") and not cli_args.get("render") and not cli_args.get("duplicate")

    if not finish_explicitly_passed and current_finish is False and no_other_action:
        logger.info(f"'{plugin_name}': overriding 'finish' default to None for search mode")
        cli_args["finish"] = None
