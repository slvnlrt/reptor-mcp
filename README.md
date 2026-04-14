# reptor-mcp: An MCP Server for Reptor/SysReptor

This project transforms the `reptor` CLI tool into an MCP (Model-Context-Protocol) server, exposing its powerful pentest reporting and automation features as a programmable service.

It allows other tools, scripts, or AI agents to programmatically interact with SysReptor via the MCP protocol, facilitating integration into automated workflows.

> [!WARNING]
> **Alpha Software:** The underlying `reptor` CLI tool is in alpha. Its API may change, potentially breaking `reptor-mcp`.

> [!CAUTION]
> **No Authentication:** This server has **no authentication or authorization**. It is designed for local use only. **DO NOT EXPOSE IT TO THE INTERNET OR UNTRUSTED NETWORKS.**

> [!IMPORTANT]
> **Data Sensitivity:** If you handle sensitive project data, consider the implications of sending it to LLMs via this server. Use `REPTOR_MCP_EXCLUDE_FIELDS` to strip sensitive fields before they reach the LLM.

## Features

*   **Dynamic Tool Generation:** Automatically creates MCP tools from all available `reptor` plugins (nmap, nessus, burp, zap, sslyze, etc.).
*   **Direct API Tools:** Provides structured tools for findings CRUD, schema discovery, and template management using reptor's Python API directly.
*   **Field Exclusion:** Strips sensitive fields from data before returning it to LLM clients (configurable via environment variable).
*   **Async-Safe:** Non-blocking event loop with thread-safe serialized plugin execution.

## Prerequisites

*   Python 3.10+
*   `uv` (recommended) or `pip`
*   A running [SysReptor](https://github.com/Syslifters/sysreptor) instance with an API token

## Installation

```bash
git clone https://github.com/slvnlrt/reptor-mcp.git
cd reptor-mcp
uv venv && source .venv/bin/activate
uv pip install -e .
```

This installs `reptor` and `fastmcp` automatically from PyPI. No need to clone the reptor repository separately.

<details>
<summary>Development setup (local reptor clone)</summary>

If you need to work against a local checkout of reptor (e.g. to test unreleased changes):

```bash
uv pip install -e /path/to/reptor-source
uv pip install -e .
```

Alternatively, set `REPTOR_MAIN_PATH=/path/to/reptor-source` at runtime to inject it into `sys.path`.
</details>

## Configuration

The server is configured via environment variables:

| Variable | Required | Description |
|---|---|---|
| `REPTOR_SERVER` | Yes | URL of your SysReptor instance |
| `REPTOR_TOKEN` | Yes | Your SysReptor API token |
| `REPTOR_PROJECT_ID` | No | Default project ID for operations |
| `REPTOR_MCP_INSECURE` | No | Set to `true` to disable SSL verification |
| `REQUESTS_CA_BUNDLE` | No | Path to a custom CA bundle file |
| `REPTOR_MCP_EXCLUDE_FIELDS` | No | Comma-separated field names to strip from LLM responses (e.g. `internal_notes,api_token`) |
| `REPTOR_MCP_DEBUG` | No | Set to `true` for verbose debug logging |

## Running the Server

```bash
fastmcp run mcp_server.py:mcp --transport streamable-http --port 8008
```

The server will be accessible at `http://localhost:8008/mcp/`.

## Client Connection

Connect an MCP client using a configuration like this (e.g., in `mcp_settings.json`):

```json
{
  "mcpServers": {
    "reptor-mcp": {
      "type": "streamable-http",
      "url": "http://localhost:8008/mcp/"
    }
  }
}
```

## Available Tools

### Custom Tools (Direct API)

These tools use reptor's Python API directly for structured, schema-aware operations:

| Tool | Description |
|---|---|
| `list_findings` | Lists findings with filters (status, severity, title). |
| `get_finding_details` | Gets full details of a finding by ID. |
| `get_finding_schema` | Discovers available finding fields, types, and constraints for a project. Call before `create_finding` or `patch_finding`. |
| `create_finding` | Creates a new finding from a flat data dict. |
| `patch_finding` | Updates a single field on a finding. |
| `delete_finding` | Deletes a finding by ID (requires explicit confirmation). |
| `upload_template` | Uploads a finding template from JSON or TOML. |

### Plugin Tools (Dynamic Wrappers)

The server dynamically wraps all `reptor` CLI plugins as MCP tools:

| Category | Tools |
|---|---|
| **Vulnerability Importers** | `nessus`, `burp`, `nmap`, `openvas`, `zap`, `qualys`, `sslyze` |
| **Finding Management** | `finding`, `findingfromtemplate`, `deletefindings`, `exportfindings` |
| **Project Management** | `project`, `createproject`, `deleteprojects`, `pushproject` |
| **Templates** | `template` |
| **Notes & Files** | `note`, `file` |
| **Translation** | `translate` (via DeepL) |
| **Import/Export** | `ghostwriter`, `defectdojo`, `importers`, `packarchive`, `unpackarchive` |

The exact arguments for each tool can be inspected via a connected MCP client.

## Relationship to reptor's Native MCP Server

Since reptor v0.33, reptor includes its own built-in MCP server (`reptor mcp`). The two servers are **complementary**:

| Capability | reptor-mcp | Native `reptor mcp` |
|---|---|---|
| Findings CRUD | :white_check_mark: | :white_check_mark: |
| Finding schema discovery | :white_check_mark: | :white_check_mark: |
| Report sections CRUD | :x: | :white_check_mark: |
| Vulnerability importers (nmap, nessus, burp, etc.) | :white_check_mark: | :x: |
| Project management (search, create, export, duplicate) | :white_check_mark: | :x: |
| Notes, files, translation | :white_check_mark: | :x: |
| Templates management | :white_check_mark: | :white_check_mark: |
| Field exclusion | :white_check_mark: | :white_check_mark: |

## Architecture

```text
mcp_server.py           # Server entry point, lifespan, configuration
├── tool_generator.py   # Dynamic MCP tool generation from plugin argparse definitions
│   ├── signature_utils.py  # argparse → Python function signature translation
│   └── wrapper_utils.py    # Plugin execution, stdin/stdout capture, config handling
├── custom_tools.py     # Direct API tools (findings CRUD, schema, templates)
└── tool_config.py      # Plugin exclusions, stdin consumers, config overwrite mappings
```

Key design decisions:
*   **Plugin wrappers** run in threads with a serialization lock, keeping the async event loop responsive while protecting shared state.
*   **Custom tools** use `asyncio.to_thread()` for non-blocking API calls.
*   **Field exclusion** recursively strips specified fields from all nested data structures before returning to the client.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements

This project would not be possible without the original [reptor CLI tool](https://github.com/Syslifters/reptor) developed by the SysReptor team and its contributors. `reptor-mcp` builds upon their excellent work to provide an MCP interface.
