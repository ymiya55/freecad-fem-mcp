import asyncio

from freecad_fem_mcp.server import TOOL_NAMES, create_server, get_tool_names


class FakeClient:
    def __init__(self):
        self.calls = []

    async def call_async(self, method, params):
        self.calls.append((method, params))
        return {"method": method, "params": params}


def test_fixed_tool_surface_has_no_generic_escape_hatches() -> None:
    assert TOOL_NAMES == (
        "get_status",
        "inspect_document",
        "get_selection",
        "set_view",
        "capture_gui",
        "open_model",
        "save_document",
        "create_analysis",
        "assign_material",
        "add_constraint",
        "create_mesh",
        "validate_analysis",
        "start_analysis",
        "get_job",
        "list_jobs",
        "cancel_job",
        "get_results",
        "show_result",
    )
    app = create_server(FakeClient())
    assert set(get_tool_names(app)) == set(TOOL_NAMES)


def test_tool_calls_cross_only_the_generic_bridge_boundary() -> None:
    client = FakeClient()
    app = create_server(client)
    tools = getattr(getattr(app, "_tool_manager", None), "_tools", None)
    if tools is None:
        tools = getattr(app, "_tools")
    entry = tools["get_status"]
    function = getattr(entry, "fn", entry)
    result = asyncio.run(function())
    assert result["method"] == "status"
    assert client.calls[0][0] == "status"
    assert client.calls[0][1]["action"] == "get"
