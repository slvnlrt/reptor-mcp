# tool_config.py
"""Configuration constants for reptor-mcp tool generation."""

# Plugins that should NOT be exposed as MCP tools.
# - mcp: reptor's own MCP server, makes no sense as a tool inside an MCP server
# - conf: internal configuration management
# - plugins: plugin management/development utility
EXCLUDED_PLUGINS = ["mcp", "conf", "plugins"]

# Plugins that consume stdin but don't declare it via argparse.
# A synthetic '_stdin_content' parameter is added for these.
STDIN_CONSUMING_PLUGINS = ["note", "finding"]

# Synthetic parameters that map to reptor CLI config overwrites.
CONFIG_OVERWRITE_PARAMS = {
    "note": {
        "title": {
            "config_key": "notetitle",
            "annotation": str | None,
            "default": None,
        }
    },
}

# Plugins whose args should be populated into config (get_cli_overwrite)
# rather than passed as direct constructor kwargs.
PLUGINS_REQUIRING_CONFIG_POPULATION = ["file"]
