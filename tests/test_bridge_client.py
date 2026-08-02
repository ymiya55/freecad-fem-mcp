import json

import pytest

from freecad_fem_mcp.bridge import (
    BridgeAuthError,
    BridgeClient,
    BridgeConfig,
    BridgeProtocolError,
    BridgeRemoteError,
)


class FakeTransport:
    def __init__(self, response_factory):
        self.response_factory = response_factory
        self.lines: list[str] = []

    def request(self, line: str) -> str:
        self.lines.append(line)
        return self.response_factory(line)


def test_bridge_client_sends_authenticated_single_ndjson_frame() -> None:
    def response(line: str) -> str:
        request = json.loads(line)
        return json.dumps({"id": request["id"], "result": {"ready": True}})

    transport = FakeTransport(response)
    client = BridgeClient(transport, token="secret-token")
    assert client.call("status", {"include_capabilities": True}) == {"ready": True}
    assert len(transport.lines) == 1
    request = json.loads(transport.lines[0])
    assert request["method"] == "status"
    assert request["auth"] == {"token": "secret-token"}
    assert "\n" not in transport.lines[0]


def test_bridge_client_rejects_unknown_methods_and_missing_auth() -> None:
    transport = FakeTransport(lambda _: "{}")
    with pytest.raises(BridgeProtocolError):
        BridgeClient(transport, token="secret-token").call("python", {})
    with pytest.raises(BridgeAuthError):
        BridgeClient(transport).call("status", {})


def test_bridge_client_rejects_duplicate_keys_and_non_finite_json() -> None:
    duplicate = FakeTransport(lambda _: '{"id":1,"id":1,"result":{}}')
    with pytest.raises(BridgeProtocolError):
        BridgeClient(duplicate, token="secret-token").call("status", {})
    nonfinite = FakeTransport(lambda _: '{"id":1,"result":{"x":NaN}}')
    with pytest.raises(BridgeProtocolError):
        BridgeClient(nonfinite, token="secret-token").call("status", {})


def test_bridge_client_redacts_token_from_remote_error() -> None:
    transport = FakeTransport(lambda _: '{"id":1,"error":{"message":"bad secret-token"}}')
    with pytest.raises(BridgeRemoteError, match="redacted") as caught:
        BridgeClient(transport, token="secret-token").call("status", {})
    assert "secret-token" not in str(caught.value)


def test_bridge_config_is_loopback_only() -> None:
    assert BridgeConfig(host="127.0.0.1").host == "127.0.0.1"
    with pytest.raises(ValueError):
        BridgeConfig(host="192.0.2.1")
