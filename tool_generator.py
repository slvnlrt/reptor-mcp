# tool_generator.py
import argparse
import inspect
import keyword
import logging # Needed for basic logging levels like logging.INFO, etc.
from typing import Any, TYPE_CHECKING
import io
import sys
from contextlib import redirect_stdout, suppress
import json
import tomli
from reptor.models.FindingTemplate import FindingTemplate
 
if TYPE_CHECKING:
    from fastmcp import FastMCP # Potentially for type hint: mcp_server: FastMCP
    from reptor.lib.reptor import Reptor # Potentially for type hint: reptor_instance: Reptor
 
from fastmcp.server.context import Context
from fastmcp.utilities.logging import get_logger
from rich.table import Table as RichTable
from rich.console import Console as RichConsole
# We will need FastMCP and Reptor types for type hinting if not already covered by Context
# These are now handled by the TYPE_CHECKING block above.

# Import configurations from the new tool_config.py
from tool_config import STDIN_CONSUMING_PLUGINS, CONFIG_OVERWRITE_PARAMS, PLUGINS_REQUIRING_CONFIG_POPULATION

# Import signature utility functions
from signature_utils import (
    create_tool_signature,
    build_tool_docstring,
)

# Import wrapper utility functions
from wrapper_utils import (
    prepare_cli_args_for_plugin,
    handle_stdin_redirection_and_args,
    apply_cli_config_overwrites,
    populate_config_for_special_plugins,
    adjust_project_tool_args,
    execute_plugin_and_capture_output
)

script_logger = get_logger("reptor-mcp.tool_generator") # Logger specific to this module
script_logger.setLevel(logging.INFO)

class ToolGenerator:
    # Constants STDIN_CONSUMING_PLUGINS, CONFIG_OVERWRITE_PARAMS,
    # and PLUGINS_REQUIRING_CONFIG_POPULATION are now imported from tool_config.py

    def __init__(self, mcp_server: "FastMCP", reptor_instance: "Reptor"):
        self.mcp = mcp_server
        self.reptor = reptor_instance

    def generate_tools(self):
        """
        Iterates through all loaded reptor plugins and creates
        a corresponding FastMCP tool for each one.
        """
        for name, module in self.reptor.plugin_manager.LOADED_PLUGINS.items():
            self._generate_tool_from_plugin(name, module)
        
        self._generate_list_findings_tool()
        self._generate_get_finding_details_tool()
        self._generate_upload_template_tool()

    def _generate_upload_template_tool(self):
        tool_name = "upload_template"

        params = [
            inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context),
            inspect.Parameter("template_data", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str),
        ]
        signature = inspect.Signature(parameters=params)

        def upload_template_wrapper(ctx: Context, template_data: str):
            ctx.info(f"Executing custom tool: {tool_name}")
            try:
                loaded_content = None
                with suppress(json.JSONDecodeError):
                    loaded_content = json.loads(template_data)
                if not loaded_content:
                    with suppress(tomli.TOMLDecodeError):
                        loaded_content = tomli.loads(template_data)
                if not loaded_content:
                    return "Error: Could not decode template_data (expected JSON or TOML)"

                template = FindingTemplate(loaded_content)
                
                # Capture display() output from upload_template
                f = io.StringIO()
                with redirect_stdout(f):
                    new_template = self.reptor.api.templates.upload_template(template)
                
                output = f.getvalue()
                if new_template:
                    return json.dumps(new_template.to_dict(), indent=2)
                elif output:
                    return output.strip()
                else:
                    return "Error: Failed to upload template for an unknown reason."

            except Exception as e:
                ctx.error(f"Error in {tool_name}: {e}")
                script_logger.error(f"Error in {tool_name}: {e}", exc_info=True)
                return f"Error executing {tool_name}: {str(e)}"

        upload_template_wrapper.__signature__ = signature
        upload_template_wrapper.__doc__ = """Uploads a new finding template from a JSON or TOML string.

Args:
    ctx (Context): The MCP context.
    template_data (str): A string containing the finding template in JSON or TOML format.

Returns:
    str: A JSON string of the created template, a status message, or an error.
"""
        self.mcp.tool(name=tool_name)(upload_template_wrapper)
        script_logger.info(f"Successfully generated and registered custom tool: {tool_name}")

    def _generate_list_findings_tool(self):
        tool_name = "list_findings"
        
        # Define the signature for the list_findings tool
        params = [
            inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context),
            inspect.Parameter("project_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str | None, default=None),
            inspect.Parameter("status", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str | None, default=None),
            inspect.Parameter("severity", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str | None, default=None),
            inspect.Parameter("title_contains", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str | None, default=None),
        ]
        signature = inspect.Signature(parameters=params)

        def list_findings_wrapper(ctx: Context, project_id: str | None = None, status: str | None = None, severity: str | None = None, title_contains: str | None = None):
            import json # Local import for json
            ctx.info(f"Executing custom tool: {tool_name}")
            try:
                target_project_id = project_id or self.reptor.get_config().get_project_id()
                if not target_project_id:
                    return "Error: Project ID not provided and no default project ID configured."

                # Switch to the target project context if different from current
                current_api_project_id = self.reptor.api.projects.project_id
                switched_project = False
                if target_project_id != current_api_project_id:
                    try:
                        self.reptor.api.projects.switch_project(target_project_id)
                        switched_project = True
                        ctx.info(f"Switched to project context: {target_project_id}")
                    except Exception as e_switch:
                        ctx.error(f"Error switching to project {target_project_id}: {e_switch}")
                        return f"Error: Could not switch to project {target_project_id}. Ensure it exists and you have access."
                
                findings_raw = self.reptor.api.projects.get_findings()
                
                # Restore original project context if switched
                if switched_project:
                    try:
                        self.reptor.api.projects.switch_project(current_api_project_id)
                        ctx.info(f"Switched back to original project context: {current_api_project_id}")
                    except Exception as e_switch_back:
                        ctx.warning(f"Could not switch back to original project {current_api_project_id}: {e_switch_back}")


                filtered_findings = []
                for finding_raw in findings_raw:
                    # Ensure finding_raw.data is a dict if it's an object with to_dict, or already a dict
                    finding_data_dict = {}
                    if hasattr(finding_raw.data, 'to_dict') and callable(finding_raw.data.to_dict):
                        finding_data_dict = finding_raw.data.to_dict()
                    elif isinstance(finding_raw.data, dict):
                        finding_data_dict = finding_raw.data
                    else:
                        # Fallback for unexpected data structure, or log a warning
                        ctx.warning(f"Finding data for {finding_raw.id} is not in expected dict or to_dict format. Skipping some fields.")


                    # Apply filters
                    if status and finding_raw.status and finding_raw.status.lower() != status.lower():
                        continue
                    if severity and finding_data_dict.get('severity', '').lower() != severity.lower():
                        continue
                    if title_contains and title_contains.lower() not in finding_data_dict.get('title', '').lower():
                        continue
                    
                    filtered_findings.append({
                        "id": finding_raw.id,
                        "title": finding_data_dict.get('title', 'N/A'),
                        "status": finding_raw.status,
                        "severity": finding_data_dict.get('severity', 'N/A'),
                        "cvss": finding_data_dict.get('cvss', 'N/A')
                    })
                return json.dumps(filtered_findings, indent=2)
            except Exception as e:
                ctx.error(f"Error in {tool_name}: {e}")
                script_logger.error(f"Error in {tool_name}: {e}", exc_info=True)
                return f"Error executing {tool_name}: {str(e)}"

        list_findings_wrapper.__signature__ = signature
        list_findings_wrapper.__doc__ = """Lists findings for a specified project.
Allows filtering by status, severity, and title.

Args:
    ctx (Context): The MCP context.
    project_id (str | None, optional): The ID of the project. Defaults to configured REPTOR_PROJECT_ID.
    status (str | None, optional): Filter findings by status (e.g., 'open', 'in-progress').
    severity (str | None, optional): Filter findings by severity (e.g., 'critical', 'high').
    title_contains (str | None, optional): Filter findings where the title contains this text (case-insensitive).
Returns:
    str: A JSON string representing a list of findings.
"""
        self.mcp.tool(name=tool_name)(list_findings_wrapper)
        script_logger.info(f"Successfully generated and registered custom tool: {tool_name}")

    def _generate_get_finding_details_tool(self):
        tool_name = "get_finding_details"

        params = [
            inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context),
            inspect.Parameter("finding_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str),
            inspect.Parameter("project_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str | None, default=None),
        ]
        signature = inspect.Signature(parameters=params)

        def get_finding_details_wrapper(ctx: Context, finding_id: str, project_id: str | None = None):
            import json # Local import for json
            ctx.info(f"Executing custom tool: {tool_name}")
            try:
                target_project_id = project_id or self.reptor.get_config().get_project_id()
                if not target_project_id:
                    # Although finding_id should be unique, project_id is good for context
                    # and the API client might use it.
                    ctx.warning("Project ID not provided and no default project ID configured. Proceeding with finding_id only.")
                
                # Ensure the API client is targeting the correct project if project_id is specified
                # This is important because get_finding might be relative to the current project context in API client
                current_api_project_id = self.reptor.api.projects.project_id
                switched_project = False
                if target_project_id and target_project_id != current_api_project_id:
                    try:
                        self.reptor.api.projects.switch_project(target_project_id)
                        switched_project = True
                        ctx.info(f"Switched to project context: {target_project_id} for get_finding_details")
                    except Exception as e_switch:
                        ctx.error(f"Error switching to project {target_project_id} for get_finding_details: {e_switch}")
                        # If we can't switch to the project, we can't reliably get its findings.
                        return f"Error: Could not switch to project {target_project_id} to get finding details."
                
                findings_raw = self.reptor.api.projects.get_findings()
                found_finding = None
                for f_raw in findings_raw:
                    if f_raw.id == finding_id:
                        found_finding = f_raw
                        break
                
                # Restore original project context if switched
                if switched_project:
                    try:
                        self.reptor.api.projects.switch_project(current_api_project_id)
                        ctx.info(f"Switched back to original project context: {current_api_project_id}")
                    except Exception as e_switch_back:
                        ctx.warning(f"Could not switch back to original project {current_api_project_id}: {e_switch_back}")

                if found_finding:
                    # Convert FindingRaw and its data to a serializable dict
                    # Ensure data is also converted if it's an object
                    finding_data_dict = {}
                    if hasattr(found_finding.data, 'to_dict') and callable(found_finding.data.to_dict):
                        finding_data_dict = found_finding.data.to_dict()
                    elif isinstance(found_finding.data, dict):
                        finding_data_dict = found_finding.data
                    
                    finding_dict = {
                        "id": found_finding.id,
                        "status": found_finding.status,
                        "order": found_finding.order,
                        # Add other top-level FindingRaw fields if necessary
                        "data": finding_data_dict
                    }
                    return json.dumps(finding_dict, indent=2)
                else:
                    return f"Error: Finding with ID '{finding_id}' not found in project '{target_project_id}'."
            except Exception as e:
                ctx.error(f"Error in {tool_name}: {e}")
                script_logger.error(f"Error in {tool_name}: {e}", exc_info=True)
                return f"Error executing {tool_name}: {str(e)}"

        get_finding_details_wrapper.__signature__ = signature
        get_finding_details_wrapper.__doc__ = """Retrieves the full details of a specific finding.

Args:
    ctx (Context): The MCP context.
    finding_id (str): The ID of the finding to retrieve.
    project_id (str | None, optional): The ID of the project the finding belongs to.
                                     Defaults to configured REPTOR_PROJECT_ID if finding needs project context.
Returns:
    str: A JSON string representing the finding's details.
"""
        self.mcp.tool(name=tool_name)(get_finding_details_wrapper)
        script_logger.info(f"Successfully generated and registered custom tool: {tool_name}")


    def _consolidate_actions(self, parser: argparse.ArgumentParser, plugin_name: str) -> dict[str, list[argparse.Action]]:
        """
        Consolidates argparse actions by their destination.
        Also logs the raw action details for debugging purposes.
        """
        actions_by_dest = {}
        for action in parser._actions:
            if not isinstance(action, argparse._HelpAction):
                if action.dest not in actions_by_dest:
                    actions_by_dest[action.dest] = []
                actions_by_dest[action.dest].append(action)

        script_logger.debug(f"  Grouped Actions for {plugin_name}:") # Use the module-specific script_logger
        for dest, action_group in actions_by_dest.items():
            script_logger.debug(f"    Dest: {dest}") # Use the module-specific script_logger
            for action_item in action_group:
                script_logger.debug(f"      Raw Action: type={type(action_item).__name__}, type_val={action_item.type}, default={action_item.default}, required={action_item.required}, nargs={action_item.nargs}, const={action_item.const}, choices={action_item.choices}, help={action_item.help}") # Use the module-specific script_logger
        return actions_by_dest

    def _generate_tool_from_plugin(self, name: str, module: Any):
        plugin_loader_class = module.loader
        plugin_meta = plugin_loader_class.meta
        
        script_logger.debug(f"Attempting to generate tool for plugin: {name}") # Use the module-specific script_logger
        script_logger.debug(f"  Summary: {plugin_meta.get('summary')}") # Use the module-specific script_logger

        parser = argparse.ArgumentParser(prog=name, description=plugin_meta.get('summary'))
        try:
            plugin_loader_class.add_arguments(parser, plugin_filepath=module.__file__)
        except Exception as e:
            script_logger.error(f"Failed to add arguments for plugin {name}: {e}", exc_info=True) # Use the module-specific script_logger
            return

        actions_by_dest = self._consolidate_actions(parser, name)
        
        # Call the utility function for creating the signature
        signature = create_tool_signature(
            name,
            actions_by_dest,
            STDIN_CONSUMING_PLUGINS, # Pass the imported constant
            CONFIG_OVERWRITE_PARAMS  # Pass the imported constant
        )
        if signature is None:
            return

        tool_wrapper = self._create_tool_wrapper(name, signature, plugin_loader_class)
        # Call the utility function for building the docstring
        tool_wrapper.__doc__ = build_tool_docstring(name, signature, plugin_meta, actions_by_dest)

        # Log the signature of the generated tool_wrapper
        # tool_wrapper.__signature__ is set at the end of _create_tool_wrapper
        script_logger.info(f"Generated wrapper for '{name}' with signature: {getattr(tool_wrapper, '__signature__', 'Not Set')}")
        # Also log to ctx if available, though ctx is not directly available in _generate_tool_from_plugin
        # For now, script_logger is sufficient for startup debugging.

        mcp_tool_name = name
        if keyword.iskeyword(mcp_tool_name):
            mcp_tool_name += "_"
        
        try:
            self.mcp.tool(name=mcp_tool_name)(tool_wrapper)
            script_logger.info(f"Successfully generated and registered tool: {mcp_tool_name}") # Use the module-specific script_logger
        except Exception as e:
            script_logger.error(f"ERROR registering tool {mcp_tool_name} with FastMCP: {e}", exc_info=True) # Use the module-specific script_logger


    # Method _create_tool_signature has been moved to signature_utils.py
    # and is called as create_tool_signature()

    def _create_tool_wrapper(self, name: str, signature: inspect.Signature, plugin_loader_class: Any) -> callable:
        # This method now orchestrates calls to helper functions in wrapper_utils.py
        
        # Pass the necessary constants from tool_config.py (already imported at class level)
        # to the helper functions if they need them directly, or rely on them being available
        # in the scope where wrapper_utils functions are defined if they also import them.
        # For clarity, it's often better to pass them if they are not class members of ToolGenerator.

        def tool_wrapper(ctx: Context, **kwargs):
            ctx.info(f"--- Entered tool_wrapper for tool: '{name}' ---")
            script_logger.info(f"--- tool_wrapper: '{name}', raw kwargs: {kwargs} ---")

            # 1. Prepare initial cli_args from MCP kwargs and signature defaults
            cli_args = prepare_cli_args_for_plugin(signature, kwargs)
            ctx.debug(f"Initial cli_args for '{name}': {cli_args}")

            # 2. Handle stdin redirection (if applicable) and update cli_args
            # STDIN_CONSUMING_PLUGINS is available via class-level import
            stdin_redirect_manager, cli_args = handle_stdin_redirection_and_args(
                name, cli_args, kwargs
            )
            
            with stdin_redirect_manager: # Manages sys.stdin restoration
                # 3. Apply CLI config overwrites (if applicable) and update cli_args
                # CONFIG_OVERWRITE_PARAMS is available via class-level import
                if self.reptor:
                    apply_cli_config_overwrites(
                        self.reptor.get_config(), name, kwargs, cli_args
                    )
                else:
                    error_msg = f"Reptor instance not available for config overwrites in tool '{name}'"
                    ctx.error(error_msg)
                    script_logger.error(error_msg)
                    return f"Error: Reptor instance not initialized for tool {name}."

                # 4. Log effective cli_args and SSL config state before plugin instantiation
                ctx.info(f"Effective cli_args for plugin '{name}': {cli_args}")
                script_logger.info(f"Effective cli_args for plugin '{name}': {cli_args}")
                if self.reptor:
                    config = self.reptor.get_config()
                    ctx.info(f"Config 'insecure': {config.get('insecure', 'N/A')}, 'requests_ca_bundle': {config.get('requests_ca_bundle', 'N/A')}, 'server': {config.get('server', 'N/A')}")
                    script_logger.info(f"Config 'insecure': {config.get('insecure', 'N/A')}, 'requests_ca_bundle': {config.get('requests_ca_bundle', 'N/A')}, 'server': {config.get('server', 'N/A')}")

                # 5. Special argument adjustments (e.g., for 'project' tool)
                adjust_project_tool_args(name, cli_args, kwargs, signature, ctx)

                # 6. Instantiate the plugin
                instance = None
                try:
                    if self.reptor:
                        # PLUGINS_REQUIRING_CONFIG_POPULATION is available via class-level import
                        was_special_population = populate_config_for_special_plugins(
                            self.reptor.get_config(), name, cli_args, ctx
                        )

                        if was_special_population:
                            ctx.info(f"PRE-instantiating '{name}' (config-populating)...")
                            instance = plugin_loader_class(reptor=self.reptor)
                            ctx.info(f"POST-instantiating '{name}' (config-populating).")
                        else:
                            ctx.info(f"PRE-instantiating '{name}' (default with cli_args)...")
                            instance = plugin_loader_class(reptor=self.reptor, **cli_args)
                            ctx.info(f"POST-instantiating '{name}' (default with cli_args).")
                    else:
                        # This case should ideally be caught earlier or handled more gracefully
                        # For now, raising to ensure it's logged and fails clearly.
                        raise RuntimeError("Reptor instance is not initialized before plugin instantiation.")
                        
                except Exception as e_inst:
                    ctx.error(f"Error instantiating plugin '{name}': {e_inst}")
                    script_logger.error(f"ERROR instantiating plugin {name}: {e_inst}", exc_info=True)
                    return f"Error instantiating tool {name}: {str(e_inst)}"

                if instance is None: # Should be caught by the except block above if instantiation failed
                    err_msg = f"Failed to instantiate plugin '{name}' (instance is None after try-except)."
                    ctx.error(err_msg)
                    script_logger.error(err_msg)
                    return err_msg
                
                # 7. Execute the plugin and capture output
                result = execute_plugin_and_capture_output(instance, name, ctx)
                return result

        tool_wrapper.__signature__ = signature
        tool_wrapper.__annotations__ = {
            p.name: p.annotation
            for p in signature.parameters.values()
            if p.annotation is not inspect.Parameter.empty
        }
        return tool_wrapper