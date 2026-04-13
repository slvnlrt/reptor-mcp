# custom_tools.py
"""
Custom MCP tools using reptor's direct Python API.

These complement the dynamically-generated CLI plugin wrappers by providing
a cleaner, structured interface for frequently-used operations like
findings CRUD, schema discovery, and template management.
"""
import json
import logging
from contextlib import suppress
from typing import Any, TYPE_CHECKING

import tomli
from fastmcp.server.context import Context
from fastmcp.utilities.logging import get_logger
from reptor.models.FindingTemplate import FindingTemplate

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from reptor.lib.reptor import Reptor

logger = get_logger("reptor-mcp.custom_tools")


# ---------------------------------------------------------------------------
# FieldExcluder
# ---------------------------------------------------------------------------

class FieldExcluder:
    """Recursively removes specified field names from nested data structures.

    Used to strip sensitive fields before returning data to LLM clients.
    Configure via the REPTOR_MCP_EXCLUDE_FIELDS environment variable.
    """

    def __init__(self, fields: list[str]):
        self._fields = set(fields)

    def exclude(self, data: dict[str, Any]) -> dict[str, Any]:
        if not self._fields or not isinstance(data, dict):
            return data
        result: dict[str, Any] = {}
        for key, value in data.items():
            if key in self._fields:
                continue
            if isinstance(value, dict):
                result[key] = self.exclude(value)
            elif isinstance(value, list):
                result[key] = [
                    self.exclude(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_project(reptor: "Reptor", project_id: str | None = None) -> str:
    """Resolve the target project ID and initialize the API context."""
    target = project_id or reptor.get_active_project_id()
    if not target:
        raise ValueError(
            "No project ID. Set REPTOR_PROJECT_ID env var, use 'reptor conf', "
            "or pass project_id explicitly."
        )
    reptor.api.projects.init_project(target)
    return target


def _finding_data_to_dict(finding_data: Any) -> dict[str, Any]:
    """Safely convert a finding's data attribute to a plain dict."""
    if hasattr(finding_data, "to_dict") and callable(finding_data.to_dict):
        return finding_data.to_dict()
    if isinstance(finding_data, dict):
        return finding_data
    return {}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_custom_tools(
    mcp: "FastMCP",
    reptor: "Reptor",
    field_excluder: FieldExcluder | None = None,
) -> None:
    """Register all custom tools on the MCP server."""

    # -- list_findings -------------------------------------------------------

    @mcp.tool(name="list_findings")
    async def list_findings(
        ctx: Context,
        project_id: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        title_contains: str | None = None,
    ) -> str:
        """Lists findings for a project with optional filters.

        Args:
            project_id: Override the configured project ID.
            status: Filter by finding status (e.g. 'in-progress').
            severity: Filter by severity (e.g. 'critical', 'high').
            title_contains: Filter by title substring (case-insensitive).

        Returns:
            JSON array of finding summaries (id, title, status, severity, cvss).
        """
        try:
            target = _resolve_project(reptor, project_id)
            await ctx.info(f"Listing findings for project {target}")

            results = []
            for f in reptor.api.projects.get_findings():
                data = _finding_data_to_dict(f.data)

                if status and (f.status or "").lower() != status.lower():
                    continue
                if severity and data.get("severity", "").lower() != severity.lower():
                    continue
                if title_contains and title_contains.lower() not in data.get("title", "").lower():
                    continue

                summary: dict[str, Any] = {
                    "id": f.id,
                    "title": data.get("title", "N/A"),
                    "status": f.status,
                    "severity": data.get("severity", "N/A"),
                    "cvss": data.get("cvss", "N/A"),
                }
                if field_excluder:
                    summary = field_excluder.exclude(summary)
                results.append(summary)

            return json.dumps(results, indent=2)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"list_findings failed: {e}", exc_info=True)
            return f"Error: {e}"

    # -- get_finding_details -------------------------------------------------

    @mcp.tool(name="get_finding_details")
    async def get_finding_details(
        ctx: Context,
        finding_id: str,
        project_id: str | None = None,
    ) -> str:
        """Gets the full details of a specific finding by its ID.

        Args:
            finding_id: The UUID of the finding.
            project_id: Override the configured project ID.

        Returns:
            JSON object with complete finding data.
        """
        try:
            target = _resolve_project(reptor, project_id)
            await ctx.info(f"Getting finding {finding_id} from project {target}")

            finding = reptor.api.projects.get_finding(finding_id)
            result = finding.to_dict()

            if field_excluder and "data" in result:
                result["data"] = field_excluder.exclude(result["data"])

            return json.dumps(result, indent=2)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"get_finding_details failed: {e}", exc_info=True)
            return f"Error: {e}"

    # -- get_finding_schema --------------------------------------------------

    @mcp.tool(name="get_finding_schema")
    async def get_finding_schema(
        ctx: Context,
        project_id: str | None = None,
    ) -> str:
        """Gets the finding field schema for a project.

        Call this BEFORE create_finding or patch_finding to discover available
        field names, types, and constraints. Field definitions vary per project.

        Args:
            project_id: Override the configured project ID.

        Returns:
            JSON schema with project_type and finding_fields definitions.
        """
        try:
            target = _resolve_project(reptor, project_id)
            await ctx.info(f"Getting finding schema for project {target}")

            project = reptor.api.projects.project
            design = reptor.api.project_designs.get_project_design(project.project_type)

            def simplify_field(field: Any) -> dict[str, Any]:
                field_type = field.type.value if hasattr(field.type, "value") else str(field.type)
                info: dict[str, Any] = {
                    "id": field.id,
                    "type": field_type,
                    "label": field.label,
                    "required": field.required,
                }
                if field_type == "enum" and field.choices:
                    info["choices"] = [c.get("value") for c in field.choices if c.get("value")]
                if field_type == "list" and field.items:
                    info["items"] = simplify_field(field.items) if hasattr(field.items, "id") else field.items
                if field_type == "object" and field.properties:
                    info["properties"] = [simplify_field(p) for p in field.properties]
                return info

            schema = {
                "project_id": target,
                "project_type": project.project_type,
                "finding_fields": [simplify_field(f) for f in design.finding_fields],
            }
            return json.dumps(schema, indent=2)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"get_finding_schema failed: {e}", exc_info=True)
            return f"Error: {e}"

    # -- create_finding ------------------------------------------------------

    @mcp.tool(name="create_finding")
    async def create_finding(
        ctx: Context,
        data: dict[str, Any],
        project_id: str | None = None,
    ) -> str:
        """Creates a new finding. Call get_finding_schema first to discover fields.

        Provide all fields in a flat dict. Top-level finding attributes (status,
        assignee, language, template, order) are set directly; everything else is
        treated as vulnerability data (title, description, cvss, etc.).

        Args:
            data: Finding data dict. At minimum include 'title'.
            project_id: Override the configured project ID.

        Returns:
            JSON object of the created finding.
        """
        try:
            target = _resolve_project(reptor, project_id)
            await ctx.info(f"Creating finding in project {target}")

            top_level = {"status", "assignee", "language", "template", "order"}
            payload: dict[str, Any] = {}
            vuln_data: dict[str, Any] = {}
            for key, value in data.items():
                if key in top_level:
                    payload[key] = value
                else:
                    vuln_data[key] = value
            payload["data"] = vuln_data

            finding = reptor.api.projects.create_finding(payload)
            result = finding.to_dict()
            if field_excluder and "data" in result:
                result["data"] = field_excluder.exclude(result["data"])
            return json.dumps(result, indent=2)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"create_finding failed: {e}", exc_info=True)
            return f"Error: {e}"

    # -- patch_finding -------------------------------------------------------

    @mcp.tool(name="patch_finding")
    async def patch_finding(
        ctx: Context,
        finding_id: str,
        field_name: str,
        field_value: Any,
        project_id: str | None = None,
    ) -> str:
        """Updates a single field on an existing finding.

        Call get_finding_schema first to discover valid field names and types.
        Updates one field at a time; the API validates types and ignores unknowns.

        Args:
            finding_id: UUID of the finding to update.
            field_name: Field name (e.g. 'title', 'status', 'cvss').
            field_value: New value matching the field's schema type.
            project_id: Override the configured project ID.

        Returns:
            JSON object of the updated finding.
        """
        try:
            target = _resolve_project(reptor, project_id)
            await ctx.info(f"Patching finding {finding_id} field '{field_name}' in project {target}")

            top_level = {"status", "assignee", "language", "template", "order"}
            if field_name in top_level:
                payload = {field_name: field_value}
            else:
                payload = {"data": {field_name: field_value}}

            finding = reptor.api.projects.update_finding(finding_id, payload)
            result = finding.to_dict()
            if field_excluder and "data" in result:
                result["data"] = field_excluder.exclude(result["data"])
            return json.dumps(result, indent=2)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"patch_finding failed: {e}", exc_info=True)
            return f"Error: {e}"

    # -- delete_finding ------------------------------------------------------

    @mcp.tool(name="delete_finding")
    async def delete_finding(
        ctx: Context,
        finding_id: str,
        project_id: str | None = None,
    ) -> str:
        """Deletes a finding by its ID.

        Args:
            finding_id: UUID of the finding to delete.
            project_id: Override the configured project ID.

        Returns:
            Confirmation message.
        """
        try:
            target = _resolve_project(reptor, project_id)
            await ctx.info(f"Deleting finding {finding_id} from project {target}")
            reptor.api.projects.delete_finding(finding_id)
            return f"Finding {finding_id} deleted successfully."
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"delete_finding failed: {e}", exc_info=True)
            return f"Error: {e}"

    # -- upload_template -----------------------------------------------------

    @mcp.tool(name="upload_template")
    async def upload_template(
        ctx: Context,
        template_data: str,
    ) -> str:
        """Uploads a finding template from a JSON or TOML string.

        Args:
            template_data: Template content as a JSON or TOML string.

        Returns:
            JSON of the created template, or an error message.
        """
        try:
            await ctx.info("Uploading finding template")

            loaded = None
            with suppress(json.JSONDecodeError):
                loaded = json.loads(template_data)
            if not loaded:
                with suppress(tomli.TOMLDecodeError):
                    loaded = tomli.loads(template_data)
            if not loaded:
                return "Error: Could not parse template_data as JSON or TOML."

            template = FindingTemplate(loaded)
            new_template = reptor.api.templates.upload_template(template)
            if new_template:
                return json.dumps(new_template.to_dict(), indent=2)
            return "Error: Template upload returned no result."
        except Exception as e:
            logger.error(f"upload_template failed: {e}", exc_info=True)
            return f"Error: {e}"

    logger.info("Registered 7 custom tools")
