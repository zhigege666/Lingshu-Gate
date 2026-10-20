"""Closed adapters for business accounts; discovery alone never authorizes secrets."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from lingshu_gate.domain.business_credentials import BusinessCredentialError
from lingshu_gate.models import ToolDefinition


# Tools which can read the host, export browser state, inject arbitrary code or
# redirect the browser process are deliberately absent. Unknown future tools
# fail closed until the adapter, its tests and its documentation are reviewed.
BROWSER_FIELDS: dict[str, frozenset[str]] = {
    "open": frozenset({"url"}),
    "back": frozenset(), "forward": frozenset(), "reload": frozenset(),
    "snapshot": frozenset({"interactive", "compact", "depth", "selector", "includeUrls", "delta", "full"}),
    "click": frozenset({"selector", "newTab", "human"}),
    "fill": frozenset({"selector", "text"}),
    "type": frozenset({"selector", "text", "clear", "delayMs"}),
    "press": frozenset({"key"}),
    "hover": frozenset({"selector"}), "focus": frozenset({"selector"}),
    "check": frozenset({"selector"}), "uncheck": frozenset({"selector"}),
    "select": frozenset({"selector", "values"}),
    "scroll": frozenset({"direction", "amount", "selector"}),
    "wait_ms": frozenset({"ms"}),
    "wait_for_selector": frozenset({"selector", "waitTimeoutMs"}),
    "wait_for_text": frozenset({"text", "waitTimeoutMs"}),
    "wait_for_url": frozenset({"url", "waitTimeoutMs"}),
    "wait_for_load": frozenset({"state", "waitTimeoutMs"}),
    "get_text": frozenset({"selector"}), "get_count": frozenset({"selector"}),
    "is_visible": frozenset({"selector"}), "is_enabled": frozenset({"selector"}),
    "is_checked": frozenset({"selector"}),
    "get_url": frozenset(), "get_title": frozenset(), "close": frozenset(),
}


def origin(url: str) -> tuple[str, str, int]:
    try:
        value = urlsplit(url)
        if (value.scheme not in {"http", "https"} or not value.hostname
                or value.username is not None or value.password is not None
                or any(ord(char) <= 32 for char in url)):
            raise ValueError
        return value.scheme, value.hostname.lower(), value.port or (443 if value.scheme == "https" else 80)
    except (ValueError, TypeError):
        raise BusinessCredentialError("invalid_browser_url", "Use an HTTP(S) URL without embedded credentials.", 422) from None


def reject_cli_options(value: Any) -> None:
    """Native positional arguments also cross its global command-line parser.

    A field allowlist alone cannot stop e.g. select.values from introducing a
    later --session or --cdp option. Passwords use stdin and are checked apart.
    """
    if isinstance(value, str) and value.startswith("-"):
        raise BusinessCredentialError("browser_option_value_denied",
            "Browser argument values starting with a hyphen are unsupported by this adapter.", 422)
    if isinstance(value, dict):
        for item in value.values():
            reject_cli_options(item)
    elif isinstance(value, list):
        for item in value:
            reject_cli_options(item)


class AgentBrowserCredentialAdapter:
    """agent-browser auth/state contract with fixed fields and explicit sessions."""

    id = "agent_browser"

    def tool(self, prefix: str, action: str) -> str:
        if prefix not in {"agent_browser_", ""}:
            raise BusinessCredentialError("unsupported_adapter", "Unsupported browser tool prefix.", 422)
        return prefix + action

    def check_contract(self, definition: ToolDefinition, action: str) -> None:
        required_fields = {
            "auth_save": {"name": "string", "url": "string", "username": "string", "password": "string"},
            "auth_login": {"name": "string", "session": "string", "noNavigate": "boolean"},
            "auth_delete": {"name": "string"}, "open": {"url": "string", "session": "string"},
        }
        properties = definition.input_schema.get("properties", {})
        if not isinstance(properties, dict) or any(
            not isinstance(properties.get(name), dict) or properties[name].get("type") != kind
            for name, kind in required_fields.get(action, {"session": "string"}).items()
        ):
            raise BusinessCredentialError("adapter_contract_incompatible",
                "The target must expose the reviewed agent-browser state/session contract.", 409)

    def save_arguments(self, record: dict[str, Any], binding: dict[str, Any], secret: dict[str, str]) -> dict[str, Any]:
        result: dict[str, Any] = {"name": binding["profile_name"], "url": record["login_url"],
                                  "username": secret["username"], "password": secret["password"]}
        for source, target in (("username", "usernameSelector"), ("password", "passwordSelector"), ("submit", "submitSelector")):
            if record["selectors"].get(source):
                result[target] = record["selectors"][source]
        reject_cli_options({key: value for key, value in result.items() if key != "password"})
        return result

    def browser_arguments(self, action: str, values: dict[str, Any], *, native_session: str,
                          login_url: str) -> dict[str, Any]:
        allowed = BROWSER_FIELDS.get(action)
        if allowed is None:
            raise BusinessCredentialError("managed_browser_tool_denied",
                "This tool is unavailable on a credential-managed browser instance.", 403)
        if set(values) - allowed - {"session", "timeoutMs"}:
            raise BusinessCredentialError("managed_browser_arguments_denied",
                "Use only reviewed browser fields and an explicit logical session; process overrides are prohibited.", 422)
        if "timeoutMs" in values and (type(values["timeoutMs"]) is not int or not 1 <= values["timeoutMs"] <= 120000):
            raise BusinessCredentialError("invalid_browser_timeout", "timeoutMs must be between 1 and 120000.", 422)
        reject_cli_options(values)
        if action in {"open", "wait_for_url"}:
            if origin(values.get("url", "")) != origin(login_url):
                raise BusinessCredentialError("credential_origin_mismatch", "This session is bound to the configured login origin.", 403)
        return {**values, "session": native_session}

    @staticmethod
    def succeeded(result: dict[str, Any]) -> bool:
        """MCP and CLI failures stay failures; malformed responses are uncertain."""
        if not isinstance(result, dict) or result.get("isError") is True:
            return False
        structured = result.get("structuredContent")
        if not isinstance(structured, dict) or type(structured.get("exitCode")) is not int or structured["exitCode"] != 0:
            return False
        response = structured.get("response")
        return isinstance(response, dict) and response.get("success") is True and isinstance(response.get("data"), dict)

    def receipt(self, result: dict[str, Any], action: str, *, profile: str | None = None,
                login_url: str | None = None) -> bool:
        if not self.succeeded(result):
            return False
        data = result["structuredContent"]["response"]["data"]
        if action == "auth_save":
            return profile is not None and data.get("saved") == profile
        if action == "auth_delete":
            return profile is not None and data.get("deleted") == profile
        if action == "auth_login":
            return profile is not None and data.get("loggedIn") is True and data.get("name") == profile
        if action == "close":
            return data.get("closed") is True
        if action == "open":
            try:
                return isinstance(data.get("url"), str) and login_url is not None and origin(data["url"]) == origin(login_url)
            except BusinessCredentialError:
                return False
        return False


ADAPTERS = {"agent_browser": AgentBrowserCredentialAdapter()}
