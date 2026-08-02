import json

import pytest

import freecad_fem_mcp.bridge as bridge_module
from freecad_fem_mcp.bridge import (
    BridgeAuthError,
    BridgeClient,
    BridgeConfig,
    BridgeProtocolError,
    BridgeRemoteError,
    BridgeTransportError,
    BRIDGE_METHODS,
    inspect_connection_record,
    load_connection_record,
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


def test_bridge_allow_list_includes_typed_load_operations() -> None:
    assert {"load", "remote_load", "boundary_condition"}.issubset(BRIDGE_METHODS)


def test_windows_pid_check_uses_read_only_helper_not_os_kill(monkeypatch) -> None:
    checked: list[int] = []

    monkeypatch.setattr(bridge_module.os, "name", "nt")
    monkeypatch.setattr(
        bridge_module,
        "_is_windows_pid_alive",
        lambda pid: checked.append(pid) or True,
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("os.kill must not run on the Windows PID branch")

    monkeypatch.setattr(bridge_module.os, "kill", fail_if_called)
    assert bridge_module.is_pid_alive(4242)
    assert checked == [4242]


def _write_record(path, *, token: str, pid: int = 1234, port: int = 8765, **extra) -> None:
    payload = {
        "host": "127.0.0.1",
        "port": port,
        "token": token,
        "protocol": "ndjson-v1",
        "pid": pid,
        **extra,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_connection_record_diagnostic_is_safe_and_detects_stale_pid(tmp_path) -> None:
    token = "old-token-" + "x" * 24
    record = tmp_path / "bridge-v1.json"
    _write_record(record, token=token, pid=4242)

    diagnostic = inspect_connection_record(record, pid_checker=lambda _: False)
    assert diagnostic.status == "stale"
    assert diagnostic.state == "stale"
    assert not diagnostic.usable
    assert token not in diagnostic.reason
    assert str(record) not in diagnostic.reason
    assert load_connection_record(record, pid_checker=lambda _: False) is None


def test_connection_record_unknown_fields_are_invalid_without_echoing_path(tmp_path) -> None:
    record = tmp_path / "private-record.json"
    _write_record(record, token="token-" + "y" * 28, pid=4242, unexpected="secret")

    diagnostic = inspect_connection_record(record, pid_checker=lambda _: True)
    assert diagnostic.status == "invalid"
    assert str(record) not in diagnostic.reason
    assert "secret" not in diagnostic.reason


class OneShotReconnectTransport:
    def __init__(self, *, fail_count: int = 1):
        self.fail_count = fail_count
        self.lines: list[str] = []

    def request(self, line: str) -> str:
        self.lines.append(line)
        if len(self.lines) <= self.fail_count:
            raise BridgeTransportError("unable to reach local FreeCAD bridge")
        request = json.loads(line)
        return json.dumps({"id": request["id"], "result": {"ready": True}})


def test_bridge_client_refreshes_record_once_after_transport_failure(tmp_path) -> None:
    record = tmp_path / "bridge-v1.json"
    old_token = "old-token-" + "a" * 24
    new_token = "new-token-" + "b" * 24
    _write_record(record, token=new_token, pid=4242, port=9876)
    transport = OneShotReconnectTransport()
    client = BridgeClient(
        transport,
        token=old_token,
        record_path=record,
        pid_checker=lambda _: True,
    )

    assert client.call("status", {}) == {"ready": True}
    assert len(transport.lines) == 2
    assert json.loads(transport.lines[0])["auth"]["token"] == old_token
    assert json.loads(transport.lines[1])["auth"]["token"] == new_token


def test_bridge_client_bootstraps_auth_from_ready_record(tmp_path) -> None:
    record = tmp_path / "bridge-v1.json"
    token = "boot-token-" + "b" * 24
    _write_record(record, token=token, pid=4242)
    transport = OneShotReconnectTransport(fail_count=0)
    client = BridgeClient(transport, record_path=record, pid_checker=lambda _: True)

    assert client.call("status", {}) == {"ready": True}
    assert json.loads(transport.lines[0])["auth"]["token"] == token


def test_bridge_client_does_not_retry_stale_record_or_over_retry(tmp_path) -> None:
    stale_record = tmp_path / "stale.json"
    stale_token = "test-token-stale-" + "s" * 24
    _write_record(stale_record, token=stale_token, pid=9999)
    stale_transport = OneShotReconnectTransport(fail_count=3)
    stale_client = BridgeClient(
        stale_transport,
        token=stale_token,
        record_path=stale_record,
        pid_checker=lambda _: False,
    )
    with pytest.raises(BridgeTransportError):
        stale_client.call("status", {})
    assert len(stale_transport.lines) == 1

    fresh_record = tmp_path / "fresh.json"
    fresh_token = "test-token-fresh-" + "f" * 24
    _write_record(fresh_record, token=fresh_token, pid=4242)
    transport = OneShotReconnectTransport(fail_count=3)
    client = BridgeClient(
        transport,
        token=fresh_token,
        record_path=fresh_record,
        pid_checker=lambda _: True,
    )
    with pytest.raises(BridgeTransportError):
        client.call("status", {})
    assert len(transport.lines) == 2
