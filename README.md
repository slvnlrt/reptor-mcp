\# reptor-mcp: An MCP Server for Reptor/SysReptor



This project transforms the `reptor` CLI tool into an MCP (Model-Context-Protocol) server, exposing its powerful pentest reporting and automation features as a programmable service.



It allows other tools, scripts, or AI agents to programmatically interact with SysReptor via the MCP protocol, facilitating integration into automated workflows.



\## ❗ Important Warnings ❗



\*   \*\*Alpha Software Stability:\*\* The underlying `reptor` CLI tool is currently in an alpha stage of development. This means its API and functionalities might change, potentially leading to breaking changes in `reptor-mcp`. While `reptor-mcp` aims for stability, its functionality is dependent on `reptor`.

\*   \*\*No MCP Server Authentication:\*\* The `reptor-mcp` server currently \*\*does not implement any authentication or authorization mechanisms\*\*. It is designed for local use. \*\*DO NOT EXPOSE THE MCP SERVER DIRECTLY TO THE INTERNET OR UNTRUSTED NETWORKS.\*\*

\*   \*\*Data Sensitivity with LLMs:\*\* If you are using `reptor`, SysReptor, and consequently `reptor-mcp` with sensitive project data, carefully consider the implications of sending this data to Large Language Models (LLMs) or any third-party services via clients connected to this MCP server. This is a general consideration for any workflow involving sensitive data and AI models.



\## Features



\*   Dynamic Tool Generation: Automatically creates MCP tools from all available `reptor` plugins.

\*   Complex Argument Handling: Manages `stdin` redirection, configuration overwrites, and special file types.

\*   Custom Tools: Includes `list\_findings`, `get\_finding\_details`, and `upload\_template` for enhanced usability.

\*   Stable \& Reliable: Built with `FastMCP` for robust server operation.



\## Prerequisites



\*   Python 3.9+

\*   `uv` (recommended for package and virtual environment management) or `pip`

\*   An existing clone of the original \[reptor CLI tool](https://github.com/SysReptor/reptor) (see Installation).



\## Project Structure



This project is designed to work alongside the original `reptor` CLI tool. For the server to function correctly, you should have the following directory structure, where both projects are siblings:



&nbsp;   your\_workspace/

&nbsp;   ├── reptor-main/      # The original reptor CLI project

&nbsp;   └── reptor-mcp/       # This project (reptor-mcp)



\## Installation



1\.  \*\*Prepare Repositories:\*\*

&nbsp;   If you haven't already, clone both `reptor-mcp` (this repository) and the original `reptor` into the same parent directory (`your\_workspace/` in the example above).



2\.  \*\*Navigate to `reptor-mcp`:\*\*

&nbsp;   All subsequent commands should be run from within the `reptor-mcp` directory.

&nbsp;   ```bash

&nbsp;   cd path/to/your\_workspace/reptor-mcp

&nbsp;   ```



3\.  \*\*Create and Activate Virtual Environment:\*\*

&nbsp;   ```bash

&nbsp;   # Using uv

&nbsp;   uv venv

&nbsp;   source .venv/bin/activate  # On Linux/macOS

&nbsp;   # .\\.venv\\Scripts\\Activate.ps1 # On Windows PowerShell

&nbsp;   ```



4\.  \*\*Install Dependencies:\*\*

&nbsp;   The `requirements.txt` file is configured to install `reptor` in editable mode from the sibling `reptor-main` directory.

&nbsp;   ```bash

&nbsp;   uv pip install -r requirements.txt

&nbsp;   ```



\## Configuration



The `reptor-mcp` server is configured via environment variables, which are utilized by the underlying `reptor` library:



\*   `REPTOR\_SERVER`: (Required) The URL of your SysReptor instance.

\*   `REPTOR\_TOKEN`: (Required) Your SysReptor API token.

\*   `REPTOR\_PROJECT\_ID`: (Optional) A default project ID to use for operations.

\*   `REPTOR\_MCP\_INSECURE`: (Optional) Set to `true` to disable SSL certificate verification for the SysReptor server (e.g., for self-signed certificates).

\*   `REQUESTS\_CA\_BUNDLE`: (Optional) Path to a custom CA bundle file for SSL verification.

\*   `REPTOR\_MCP\_DEBUG`: (Optional) Set to `true` to enable verbose debug logging from the `reptor-mcp` server.



\## Running the Server



The recommended way to run the server for programmatic access is with `fastmcp run` and the `streamable-http` transport:



```bash

\# From the reptor-mcp project root, after activating the virtual environment

fastmcp run mcp\_server.py:mcp --transport streamable-http --port 8008

```

The server will be accessible at `http://localhost:8008/mcp/`. \*\*Remember the security warning above: run only in trusted, local environments.\*\*



\## Client Connection



To connect an MCP client to the server, use a configuration similar to the following (e.g., in `mcp\_settings.json`):



```json

{

&nbsp; "mcpServers": {

&nbsp;   "reptor-mcp": {

&nbsp;     "type": "streamable-http",

&nbsp;     "url": "http://localhost:8008/mcp/"

&nbsp;   }

&nbsp; }

}

```



\## Available Tools



The server dynamically generates tools from all available `reptor` plugins. This includes tools like `note`, `finding`, `project`, `file`, `nmap`, `burp`, and more.



Additionally, the following custom tools are available for enhanced usability:



\*   `list\_findings`: Lists findings for a project, with options to filter by status, severity, and title.

\*   `get\_finding\_details`: Retrieves the full, detailed JSON object for a specific finding by its ID.

\*   `upload\_template`: Uploads a new finding template from a JSON or TOML string.



The exact arguments for each tool can be inspected via a connected MCP client.



\## Architecture Overview



`reptor-mcp` acts as a dynamic wrapper around the `reptor` CLI. It uses `FastMCP` to expose `reptor`'s functionalities as MCP tools.

Key components include:

\*   `mcp\_server.py`: Main server entry point.

\*   `tool\_generator.py`: Dynamically generates MCP tools from `reptor` plugins by inspecting their `argparse` definitions.

\*   `signature\_utils.py`: Helps translate `argparse` definitions to Python function signatures.

\*   `wrapper\_utils.py`: Contains the core logic for executing the wrapped `reptor` plugins, handling arguments, `stdin`, and output.

\*   `tool\_config.py`: Manages special configurations for certain plugins.



This approach allows `reptor-mcp` to leverage `reptor`'s tested logic while providing a modern, programmatic interface, without modifying the original `reptor` codebase.



\## License



This project is licensed under the MIT License - see the \[LICENSE](LICENSE) file for details.



\## Acknowledgements



This project would not be possible without the original \[reptor CLI tool](https://github.com/SysReptor/reptor) developed by the SysReptor team and its contributors. `reptor-mcp` builds upon their excellent work to provide an MCP interface.

