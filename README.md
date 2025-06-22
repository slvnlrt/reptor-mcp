# reptor-mcp: An MCP Server for Reptor/SysReptor

This project transforms the `reptor` CLI tool into an MCP (Model-Context-Protocol) server, exposing its powerful pentest reporting and automation features as a programmable service.

It allows other tools, scripts, or AI agents to programmatically interact with SysReptor via the MCP protocol, facilitating integration into automated workflows.

## ❗ Important Warnings ❗

*   **Alpha Software Stability:** The underlying `reptor` CLI tool is currently in an alpha stage of development. This means its API and functionalities might change, potentially leading to breaking changes in `reptor-mcp`. While `reptor-mcp` aims for stability, its functionality is dependent on `reptor`.
*   **No MCP Server Authentication:** The `reptor-mcp` server currently **does not implement any authentication or authorization mechanisms**. It is designed for local use. **DO NOT EXPOSE THE MCP SERVER DIRECTLY TO THE INTERNET OR UNTRUSTED NETWORKS.**
*   **Data Sensitivity with LLMs:** If you are using `reptor`, SysReptor, and consequently `reptor-mcp` with sensitive project data, carefully consider the implications of sending this data to Large Language Models (LLMs) or any third-party services via clients connected to this MCP server. This is a general consideration for any workflow involving sensitive data and AI models.

## Features

*   Dynamic Tool Generation: Automatically creates MCP tools from all available `reptor` plugins.
*   Complex Argument Handling: Manages `stdin` redirection, configuration overwrites, and special file types.
*   Custom Tools: Includes `list_findings`, `get_finding_details`, and `upload_template` for enhanced usability.
*   Stable & Reliable: Built with `FastMCP` for robust server operation.

## Prerequisites

*   Python 3.9+
*   `uv` (recommended for package and virtual environment management) or `pip`
*   An existing clone of the original [reptor CLI tool](https://github.com/Syslifters/reptor) (see Installation).

## Project Structure

This project is designed to work alongside the original `reptor` CLI tool. For the server to function correctly, you should have the following directory structure, where both projects are siblings:

    your_workspace/
    ├── reptor-main/      # The original reptor CLI project
    └── reptor-mcp/       # This project (reptor-mcp)

## Installation

1.  **Prepare Repositories:**
    If you haven't already, clone both `reptor-mcp` (this repository) and the original `reptor` into the same parent directory (`your_workspace/` in the example above).

2.  **Navigate to `reptor-mcp`:**
    All subsequent commands should be run from within the `reptor-mcp` directory.
    ```bash
    cd path/to/your_workspace/reptor-mcp
    ```

3.  **Create and Activate Virtual Environment:**
    ```bash
    # Using uv
    uv venv
    source .venv/bin/activate  # On Linux/macOS
    # .\.venv\Scripts\Activate.ps1 # On Windows PowerShell
    ```

4.  **Install Dependencies:**
    The `requirements.txt` file is configured to install `reptor` in editable mode from the sibling `reptor-main` directory.
    ```bash
    uv pip install -r requirements.txt
    ```

## Configuration

The `reptor-mcp` server is configured via environment variables, which are utilized by the underlying `reptor` library:

*   `REPTOR_SERVER`: (Required) The URL of your SysReptor instance.
*   `REPTOR_TOKEN`: (Required) Your SysReptor API token.
*   `REPTOR_PROJECT_ID`: (Optional) A default project ID to use for operations.
*   `REPTOR_MCP_INSECURE`: (Optional) Set to `true` to disable SSL certificate verification for the SysReptor server (e.g., for self-signed certificates).
*   `REQUESTS_CA_BUNDLE`: (Optional) Path to a custom CA bundle file for SSL verification.
*   `REPTOR_MCP_DEBUG`: (Optional) Set to `true` to enable verbose debug logging from the `reptor-mcp` server.

## Running the Server

The recommended way to run the server for programmatic access is with `fastmcp run` and the `streamable-http` transport:

```bash
# From the reptor-mcp project root, after activating the virtual environment
fastmcp run mcp_server.py:mcp --transport streamable-http --port 8008
```
The server will be accessible at `http://localhost:8008/mcp/`. **Remember the security warning above: run only in trusted, local environments.**

## Client Connection

To connect an MCP client to the server, use a configuration similar to the following (e.g., in `mcp_settings.json`):

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

The server dynamically generates tools from all available `reptor` plugins. This includes tools like `note`, `finding`, `project`, `file`, `nmap`, `burp`, and more.

Additionally, the following custom tools are available for enhanced usability:

*   `list_findings`: Lists findings for a project, with options to filter by status, severity, and title.
*   `get_finding_details`: Retrieves the full, detailed JSON object for a specific finding by its ID.
*   `upload_template`: Uploads a new finding template from a JSON or TOML string.

The exact arguments for each tool can be inspected via a connected MCP client.

## Architecture Overview

`reptor-mcp` acts as a dynamic wrapper around the `reptor` CLI. It uses `FastMCP` to expose `reptor`'s functionalities as MCP tools.
Key components include:
*   `mcp_server.py`: Main server entry point.
*   `tool_generator.py`: Dynamically generates MCP tools from `reptor` plugins by inspecting their `argparse` definitions.
*   `signature_utils.py`: Helps translate `argparse` definitions to Python function signatures.
*   `wrapper_utils.py`: Contains the core logic for executing the wrapped `reptor` plugins, handling arguments, `stdin`, and output.
*   `tool_config.py`: Manages special configurations for certain plugins.

This approach allows `reptor-mcp` to leverage `reptor`'s tested logic while providing a modern, programmatic interface, without modifying the original `reptor` codebase.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements

This project would not be possible without the original [reptor CLI tool](https://github.com/Syslifters/reptor) developed by the SysReptor team and its contributors. `reptor-mcp` builds upon their excellent work to provide an MCP interface.
