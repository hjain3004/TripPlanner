from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from gateway.travel.adapters.gondola.mcp_client import ALLOWED_HOST, LiveGondolaTransport
from gateway.travel.errors import TravelGatewayError


def test_constructor_accepts_the_allowlisted_host() -> None:
    LiveGondolaTransport(base_url=f"https://{ALLOWED_HOST}/mcp", get_access_token=lambda: "t")


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://evil.example.com/mcp",
        "https://mcp.gondola.ai.evil.com/mcp",
        "http://mcp.gondola.ai/mcp",  # not https
        "https://gondola.ai/mcp",  # missing mcp. subdomain
        "not-a-url",
    ],
)
def test_constructor_refuses_every_non_allowlisted_host(bad_url: str) -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        LiveGondolaTransport(base_url=bad_url, get_access_token=lambda: "t")
    assert exc_info.value.code == "permission_denied"


def test_dispatch_tool_rejects_denied_tool_before_any_network_call() -> None:
    transport = LiveGondolaTransport(
        base_url=f"https://{ALLOWED_HOST}/mcp", get_access_token=lambda: "t"
    )
    with pytest.raises(TravelGatewayError) as exc_info:
        transport.build_tool_call("book_hotel", {})
    assert exc_info.value.code == "permission_denied"


def test_dispatch_tool_rejects_unknown_tool_before_any_network_call() -> None:
    transport = LiveGondolaTransport(
        base_url=f"https://{ALLOWED_HOST}/mcp", get_access_token=lambda: "t"
    )
    with pytest.raises(TravelGatewayError) as exc_info:
        transport.build_tool_call("made_up_tool_name", {})
    assert exc_info.value.code == "permission_denied"


def test_dispatch_tool_accepts_allowlisted_tool() -> None:
    transport = LiveGondolaTransport(
        base_url=f"https://{ALLOWED_HOST}/mcp", get_access_token=lambda: "t"
    )
    name, arguments = transport.build_tool_call("search_hotels", {"city": "Singapore"})
    assert name == "search_hotels"
    assert arguments == {"city": "Singapore"}


def test_oversized_response_is_rejected_before_json_parsing() -> None:
    transport = LiveGondolaTransport(
        base_url=f"https://{ALLOWED_HOST}/mcp", get_access_token=lambda: "t"
    )
    huge_payload = b"x" * 600_000
    with pytest.raises(TravelGatewayError) as exc_info:
        transport.validate_payload_size(huge_payload)
    assert exc_info.value.code == "invalid_response"


def test_within_bound_payload_is_accepted() -> None:
    transport = LiveGondolaTransport(
        base_url=f"https://{ALLOWED_HOST}/mcp", get_access_token=lambda: "t"
    )
    transport.validate_payload_size(b"x" * 1000)  # must not raise


def test_module_is_never_imported_by_core_agents_or_api() -> None:
    backend = Path(__file__).parent.parent
    module_path = backend / "gateway" / "travel" / "adapters" / "gondola" / "mcp_client.py"
    tree = ast.parse(module_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("core.")
            assert not node.module.startswith("core ")

    for package in ("core", "accounts", "agents", "api"):
        pkg_dir = backend / package
        for py_file in pkg_dir.rglob("*.py"):
            source = py_file.read_text()
            assert "gondola.mcp_client" not in source
            assert "adapters.gondola import mcp_client" not in source


def test_no_credentials_are_read_from_environment_by_this_module() -> None:
    from gateway.travel.adapters.gondola import mcp_client as mcp_client_module

    source = inspect.getsource(mcp_client_module)
    assert "os.environ" not in source
    assert "getenv" not in source


def test_constructor_accepts_no_token_for_anonymous_use() -> None:
    # Anonymous tools (search_hotels, tools/list discovery) need no OAuth token.
    transport = LiveGondolaTransport(
        base_url=f"https://{ALLOWED_HOST}/mcp", get_access_token=lambda: None
    )
    assert transport is not None


def test_transport_exposes_a_list_tools_method() -> None:
    transport = LiveGondolaTransport(
        base_url=f"https://{ALLOWED_HOST}/mcp", get_access_token=lambda: None
    )
    assert hasattr(transport, "list_tools")
    assert inspect.iscoroutinefunction(transport.list_tools)


def _transport() -> LiveGondolaTransport:
    return LiveGondolaTransport(
        base_url=f"https://{ALLOWED_HOST}/mcp", get_access_token=lambda: None
    )


def test_unwrap_prefers_structured_content_when_present() -> None:
    from mcp.types import CallToolResult, TextContent

    result = CallToolResult(
        content=[TextContent(type="text", text='{"results": ["fallback"]}')],
        structuredContent={"results": [{"hotel_id": "h1"}]},
        isError=False,
    )
    unwrapped = _transport()._unwrap_tool_result(result)
    assert unwrapped == {"results": [{"hotel_id": "h1"}]}


def test_unwrap_falls_back_to_first_text_content_block_json() -> None:
    from mcp.types import CallToolResult, TextContent

    result = CallToolResult(
        content=[TextContent(type="text", text='{"results": [{"hotel_id": "h2"}]}')],
        structuredContent=None,
        isError=False,
    )
    unwrapped = _transport()._unwrap_tool_result(result)
    assert unwrapped == {"results": [{"hotel_id": "h2"}]}


def test_unwrap_raises_invalid_response_when_is_error_true() -> None:
    from mcp.types import CallToolResult, TextContent

    result = CallToolResult(
        content=[TextContent(type="text", text="rate limited")],
        structuredContent=None,
        isError=True,
    )
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport()._unwrap_tool_result(result)
    assert exc_info.value.code == "invalid_response"


def test_error_result_preserves_a_sanitized_bounded_error_summary() -> None:
    from mcp.types import CallToolResult, TextContent

    result = CallToolResult(
        content=[TextContent(type="text", text="Invalid parameter: depart_date must be ISO-8601")],
        structuredContent=None,
        isError=True,
    )
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport()._unwrap_tool_result(result)
    assert "Invalid parameter: depart_date must be ISO-8601" in exc_info.value.message


def test_error_summary_is_bounded_in_length_even_for_a_huge_error_text() -> None:
    from mcp.types import CallToolResult, TextContent

    from gateway.travel.adapters.gondola.mcp_client import MAX_ERROR_SUMMARY_CHARS

    huge_text = "x" * 10_000
    result = CallToolResult(
        content=[TextContent(type="text", text=huge_text)],
        structuredContent=None,
        isError=True,
    )
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport()._unwrap_tool_result(result)
    assert len(exc_info.value.message) < MAX_ERROR_SUMMARY_CHARS + 200


def test_error_result_with_no_text_content_still_raises_cleanly() -> None:
    from mcp.types import CallToolResult

    result = CallToolResult(content=[], structuredContent=None, isError=True)
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport()._unwrap_tool_result(result)
    assert exc_info.value.code == "invalid_response"


def test_unwrap_raises_invalid_response_when_nothing_parsable() -> None:
    from mcp.types import CallToolResult

    result = CallToolResult(content=[], structuredContent=None, isError=False)
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport()._unwrap_tool_result(result)
    assert exc_info.value.code == "invalid_response"


def test_unwrap_raises_invalid_response_when_structured_content_is_not_a_dict() -> None:
    from mcp.types import CallToolResult, TextContent

    result = CallToolResult(
        content=[TextContent(type="text", text="[]")],
        structuredContent=["not", "a", "dict"],
        isError=False,
    )
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport()._unwrap_tool_result(result)
    assert exc_info.value.code == "invalid_response"


def test_unwrap_raises_invalid_response_when_text_content_parses_to_a_non_dict() -> None:
    from mcp.types import CallToolResult, TextContent

    result = CallToolResult(
        content=[TextContent(type="text", text="[1, 2, 3]")],
        structuredContent=None,
        isError=False,
    )
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport()._unwrap_tool_result(result)
    assert exc_info.value.code == "invalid_response"


def test_unwrap_raises_invalid_response_on_malformed_text_json() -> None:
    from mcp.types import CallToolResult, TextContent

    result = CallToolResult(
        content=[TextContent(type="text", text="not json at all")],
        structuredContent=None,
        isError=False,
    )
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport()._unwrap_tool_result(result)
    assert exc_info.value.code == "invalid_response"
