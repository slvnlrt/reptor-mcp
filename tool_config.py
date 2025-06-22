# tool_config.py
# This file will store constants and configurations for the tool_generator.

# REPTOR-MCP: Define plugins that consume stdin, but don't declare it via argparse
# This enables a synthetic _stdin_content parameter for dynamic tool generation.
STDIN_CONSUMING_PLUGINS = ["note", "finding"]

CONFIG_OVERWRITE_PARAMS = {
    "note": {  # Plugin name
        "title": {  # Synthetic parameter name in the MCP tool
            "config_key": "notetitle",  # Key in reptor's cli_overwrite dictionary
            "annotation": str | None,   # Type annotation for the synthetic parameter
            "default": None             # Default value for the synthetic parameter
        }
    }
    # Future plugins with similar patterns can be added here
}

# Plugins that expect their arguments to be primarily read from config.get_cli_overwrite()
# rather than direct constructor kwargs, and may need special arg processing (e.g. FileType)
PLUGINS_REQUIRING_CONFIG_POPULATION = ["file"]