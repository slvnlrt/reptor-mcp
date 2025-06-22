# signature_utils.py
# Utility functions for creating and managing inspect.Signature objects
# and docstrings for the generated MCP tools.

import argparse
import inspect
import keyword
from typing import Any, Literal, Union # Added Union

# Import from tool_config for constants needed in signature creation
from tool_config import STDIN_CONSUMING_PLUGINS, CONFIG_OVERWRITE_PARAMS

# Logger - can be configured as needed, e.g. get_logger from fastmcp
import logging
from fastmcp.utilities.logging import get_logger
script_logger = get_logger("reptor-mcp.signature_utils")

def get_param_type(action: argparse.Action) -> Any:
    """
    Determines the Python type annotation for an argparse.Action.
    """
    # --- 1. Handle list types first (nargs='*', '+', or number) ---
    if action.nargs == argparse.ZERO_OR_MORE or \
       action.nargs == argparse.ONE_OR_MORE or \
       (isinstance(action.nargs, int) and action.nargs > 1):
        element_type = Any
        if action.type == str or action.type is None:
            element_type = str
        elif action.type == int:
            element_type = int
        elif action.type == float:
            element_type = float
        elif isinstance(action.type, argparse.FileType):
            element_type = str  # File paths/content as strings in a list
        elif action.type is not None: # callable, etc.
            if callable(action.type) and not isinstance(action.type, type):
                element_type = str # Custom type func like reptor's dir_or_file
            else:
                element_type = action.type # A class type
        return list[element_type]

    # --- 2. Handle specific action types (StoreTrue, StoreFalse, StoreConst, Append) ---
    elif isinstance(action, argparse._StoreTrueAction) or isinstance(action, argparse._StoreFalseAction):
        return bool
    elif isinstance(action, argparse._StoreConstAction):
        if action.const is not None:
            return type(action.const)
        elif action.default is not None:
            return type(action.default)
        return bool # Fallback
    elif isinstance(action, argparse._AppendAction):
        element_type = str
        if action.type:
            element_type = action.type
        return list[element_type]
    
    # --- 3. Handle choices (potentially creating Literal) ---
    if action.choices:
        try:
            # typing.Literal requires Python 3.8+
            return Literal[tuple(action.choices)]
        except (ImportError, AttributeError): # AttributeError for older typing.Literal
            return str # Fallback

    # --- 4. General type mapping if not covered above ---
    if action.type == str:
        return str
    elif action.type == int:
        return int
    elif action.type == float:
        return float
    elif isinstance(action.type, argparse.FileType):
        return str
    elif callable(action.type) and not isinstance(action.type, type): # Custom type func
        return str
    elif action.type is None and action.nargs != 0: # Positional/optional without type
        return str

    # --- 5. Fallback annotation ---
    if action.nargs == 0: # Boolean flag if no other type info
        return bool
    else:
        return Any # Ultimate fallback

def get_param_default(action: argparse.Action, annotation: Any) -> Any:
    """
    Determines the default value for an inspect.Parameter based on an argparse.Action.
    """
    default = inspect.Parameter.empty

    if action.default != argparse.SUPPRESS:
        default = action.default
    
    if annotation == bool and default is inspect.Parameter.empty and action.default is argparse.SUPPRESS:
        default = False

    if (action.nargs == argparse.ZERO_OR_MORE or isinstance(action.nargs, int) and action.nargs > 1) and \
       action.default is None and not action.required:
        default = []

    if isinstance(action, argparse._StoreConstAction) and action.const is not None and default == inspect.Parameter.empty :
        default = action.const

    if not action.required and default == inspect.Parameter.empty:
        if annotation == bool:
            default = False
        else:
            default = None

    if action.required and (default is None or default == inspect.Parameter.empty):
        default = inspect.Parameter.empty
    
    return default

def argparse_action_to_inspect_parameter(action: argparse.Action) -> inspect.Parameter | None:
    """
    Converts an argparse.Action object to an inspect.Parameter object.
    """
    param_name = action.dest
    kind = inspect.Parameter.POSITIONAL_OR_KEYWORD

    if param_name == "help":
        return None
    if keyword.iskeyword(param_name):
        param_name += "_"

    annotation_from_type = get_param_type(action)
    final_default = get_param_default(action, annotation_from_type)

    final_annotation = annotation_from_type
    if not action.required and final_default is None:
        is_already_optional = (
            hasattr(final_annotation, '__origin__') and
            str(final_annotation.__origin__) in ("typing.Union", "typing.Optional") and # type: ignore
            type(None) in getattr(final_annotation, '__args__', tuple())
        )
        if not is_already_optional:
            if final_annotation is bool:
                final_annotation = Union[bool, None] # type: ignore
            elif hasattr(final_annotation, '_name') and final_annotation._name == 'Literal':
                final_annotation = Union[final_annotation, type(None)] # type: ignore
            elif final_annotation is not Any:
                final_annotation = Union[final_annotation, type(None)] # type: ignore
    
    effective_default = final_default if final_default is not inspect.Parameter.empty else inspect.Parameter.empty
    effective_annotation = final_annotation if final_annotation is not inspect.Parameter.empty else inspect.Parameter.empty

    return inspect.Parameter(
        name=param_name,
        kind=kind,
        default=effective_default,
        annotation=effective_annotation
    )

def create_tool_signature(
    name: str, 
    actions_by_dest: dict[str, list[argparse.Action]],
    # Pass constants directly, or a config object containing them
    # For simplicity here, passing them directly:
    stdin_consuming_plugins_list: list[str], 
    config_overwrite_params_map: dict
) -> inspect.Signature | None:
    """
    Creates an inspect.Signature for a tool based on its argparse actions.
    """
    from fastmcp.server.context import Context # Local import to avoid circular if this becomes a very generic util

    parameters = []
    for dest, action_group in actions_by_dest.items():
        if len(action_group) > 1:
            is_potential_enum_const_group = False
            if all(isinstance(act, argparse._StoreConstAction) for act in action_group):
                const_values = {act.const for act in action_group}
                # Check if this isn't just a simple True/False flag pair (which is handled by is_true_false_pair)
                # A group of _StoreConstAction might represent a set of choices for a parameter.
                if not (len(const_values) == 1 and (True in const_values or False in const_values)):
                    is_potential_enum_const_group = True

            is_true_false_pair = len(action_group) == 2 and \
                                 ((isinstance(action_group[0], argparse._StoreTrueAction) and isinstance(action_group[1], argparse._StoreFalseAction)) or \
                                  (isinstance(action_group[0], argparse._StoreFalseAction) and isinstance(action_group[1], argparse._StoreTrueAction)))

            if is_true_false_pair:
                true_action = next((act for act in action_group if isinstance(act, argparse._StoreTrueAction)), None)
                false_action = next((act for act in action_group if isinstance(act, argparse._StoreFalseAction)), None)
                
                param_name = action_group[0].dest
                if keyword.iskeyword(param_name):
                    param_name += "_"
                param_default = False
                if true_action and false_action:
                    if true_action.default is not None: param_default = true_action.default
                    else: param_default = False
                elif true_action:
                    if true_action.default is not None: param_default = true_action.default
                    else: param_default = False
                elif false_action:
                    if false_action.default is None: param_default = True
                    else: param_default = false_action.default
                        
                param = inspect.Parameter(
                    name=param_name, kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=param_default, annotation=bool
                )
                parameters.append(param)
                script_logger.debug(f"      Consolidated Param (Bool Pair): {param}")
            
            elif is_potential_enum_const_group:
                choices = tuple(act.const for act in action_group if act.const is not None)
                default_value = inspect.Parameter.empty
                primary_action = action_group[0]
                
                for act in action_group:
                    if act.default is not None and act.default != argparse.SUPPRESS:
                        if act.default in choices:
                            default_value = act.default
                            primary_action = act
                            break
                        if default_value == inspect.Parameter.empty:
                            default_value = act.default
                            primary_action = act

                if default_value == inspect.Parameter.empty and not primary_action.required:
                    default_value = None
                
                param_name = primary_action.dest
                if keyword.iskeyword(param_name): param_name += "_"
                
                annotation = Any
                if choices:
                    try:
                        annotation = Literal[choices] # type: ignore
                        if default_value is None and not primary_action.required:
                             annotation = Union[annotation, type(None)] # type: ignore
                    except (ImportError, AttributeError):
                        annotation = str
                
                param = inspect.Parameter(
                    name=param_name, kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=default_value if default_value is not None else inspect.Parameter.empty,
                    annotation=annotation
                )
                parameters.append(param)
                script_logger.debug(f"      Consolidated Param (Literal): {param}")
            else:
                main_action = action_group[0]
                for act in action_group:
                    if act.help and act.help != argparse.SUPPRESS:
                        main_action = act
                        break
                param = argparse_action_to_inspect_parameter(main_action)
                if param:
                    parameters.append(param)
                    script_logger.debug(f"      Generated Param (from first/main action): {param}")
        else:
            param = argparse_action_to_inspect_parameter(action_group[0])
            if param:
                parameters.append(param)
                script_logger.debug(f"      Generated Param (single action): {param}")
    
    if name in stdin_consuming_plugins_list: # Use passed list
        if "_stdin_content" not in [p.name for p in parameters]:
            parameters.append(
                inspect.Parameter(
                    name="_stdin_content", kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=inspect.Parameter.empty, annotation=str
                )
            )
            script_logger.debug(f"Added REQUIRED synthetic _stdin_content parameter for plugin: {name}")

    if name in config_overwrite_params_map: # Use passed map
        for synth_param_name, synth_param_details in config_overwrite_params_map[name].items():
            if synth_param_name not in [p.name for p in parameters]:
                parameters.append(
                    inspect.Parameter(
                        name=synth_param_name, kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        default=synth_param_details.get("default", None),
                        annotation=synth_param_details.get("annotation", Any)
                    )
                )
                script_logger.debug(f"Added synthetic '{synth_param_name}' parameter for plugin: {name} (config overwrite)")

    ctx_param = inspect.Parameter(
        name="ctx", kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Context
    )
    final_parameters = [ctx_param] + parameters

    try:
        if len(final_parameters) > 1:
            params_to_sort = final_parameters[1:]
            params_to_sort.sort(key=lambda p: p.default == inspect.Parameter.empty, reverse=True)
            final_parameters = [final_parameters[0]] + params_to_sort
    except Exception as e:
        script_logger.error(f"ERROR sorting parameters for {name}: {e}. Tool generation for this plugin will be skipped.", exc_info=True)
        return None

    if not final_parameters:
        script_logger.info(f"Plugin {name} results in no parameters for signature. This is unexpected.")
    
    try:
        return inspect.Signature(parameters=final_parameters)
    except TypeError as e:
        script_logger.error(f"ERROR creating signature for {name} (TypeError): {e}. Parameters: {parameters}", exc_info=True)
        return None
    except ValueError as e:
        script_logger.error(f"ERROR creating signature for {name} (ValueError): {e}. Parameters: {parameters}", exc_info=True)
        return None

def build_tool_docstring(
    name: str, 
    signature: inspect.Signature, 
    plugin_meta: dict, 
    actions_by_dest: dict[str, list[argparse.Action]]
) -> str:
    """
    Builds a docstring for a generated MCP tool.
    """
    doc_parts = [f"{plugin_meta.get('summary', 'No description available.')}"]
    if signature.parameters:
        doc_parts.append("\n\nArgs:")
        for param in signature.parameters.values():
            p_name = param.name
            p_type_repr = str(param.annotation) if param.annotation != inspect.Parameter.empty else 'Any'
            p_type_repr = p_type_repr.replace("typing.", "").replace("typing_extensions.", "").replace("<class '", "").replace("'>", "")

            action_help = "No help available."
            if p_name == "_stdin_content":
                action_help = "Content to be passed to the tool via stdin."
                if name == "finding":
                    # Specific example for the 'finding' tool's _stdin_content
                    action_help += """
Example JSON structure:
```json
{
  "status": "in-progress",
  "data": {
    "title": "Sample Finding Title",
    "cvss": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
    "summary": "A brief summary of the finding.",
    "description": "A detailed description of the vulnerability.",
    "recommendation": "Detailed steps to mitigate or fix the vulnerability.",
    "affected_components": [
      "component1.example.com/path",
      "component2.example.com/another/path"
    ],
    "references": [
      "https://cwe.mitre.org/data/definitions/79.html"
    ]
  }
}
```
Note: For precise structure, use the `get_finding_schema` tool (if available) or refer to the target project's design in SysReptor.
"""
            else:
                original_param_dest = p_name[:-1] if p_name.endswith('_') and keyword.iskeyword(p_name[:-1]) else p_name
                if original_param_dest in actions_by_dest:
                    for act_item in actions_by_dest[original_param_dest]:
                        if act_item.help and act_item.help != argparse.SUPPRESS:
                            action_help = act_item.help
                            break
                    if action_help == "No help available." and actions_by_dest[original_param_dest]:
                        action_help = actions_by_dest[original_param_dest][0].help or "No help available."
            
            doc_line = f"    {p_name} ({p_type_repr})"
            if param.default != inspect.Parameter.empty:
                if isinstance(param.default, str) and not param.default:
                     doc_line += f" = \"\""
                elif param.default is False and param.annotation == bool:
                    pass # Default False for bool is standard
                elif param.default is None and ("Optional[" in p_type_repr or "NoneType" in p_type_repr or p_type_repr.endswith("| None")): # type: ignore
                    pass # Default None for Optional is standard
                else:
                    doc_line += f" = {param.default!r}"
            doc_line += f": {action_help}"
            doc_parts.append(doc_line)
    return "\n".join(doc_parts)