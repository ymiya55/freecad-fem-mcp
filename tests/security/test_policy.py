from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Pytest's import-prepend mode may place ``tests`` ahead of the repository
# root, making this directory look like a top-level ``security`` package.
# Pin the intended policy package explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from security.policy import (
    DuplicateKeyError,
    NDJSONError,
    PathPolicyError,
    is_loopback_host,
    parse_ndjson,
    safe_join,
)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.42.9.1", True),
        ("::1", True),
        ("[::1]", True),
        ("localhost", True),
        ("LOCALHOST.", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.1.10", False),
        ("localhost.example", False),
        ("", False),
        (None, False),
    ],
)
def test_loopback_host_is_explicit(host: object, expected: bool) -> None:
    assert is_loopback_host(host) is expected


def test_ndjson_accepts_objects_and_blank_lines() -> None:
    assert parse_ndjson(b'{"id": 1}\n\n{"nested":{"ok":true}}\n') == [
        {"id": 1},
        {"nested": {"ok": True}},
    ]


def test_ndjson_rejects_malformed_json() -> None:
    with pytest.raises(NDJSONError):
        parse_ndjson('{"id":}\n')


def test_ndjson_rejects_duplicate_keys_at_every_depth() -> None:
    with pytest.raises(DuplicateKeyError):
        parse_ndjson('{"id":1,"id":2}\n')
    with pytest.raises(DuplicateKeyError):
        parse_ndjson('{"outer":{"x":1,"x":2}}\n')


def test_ndjson_rejects_non_objects_and_non_finite_numbers() -> None:
    with pytest.raises(NDJSONError):
        parse_ndjson("[1, 2]\n")
    with pytest.raises(NDJSONError):
        parse_ndjson('{"value": NaN}\n')


def test_ndjson_enforces_line_and_total_limits() -> None:
    with pytest.raises(NDJSONError, match="line"):
        parse_ndjson('{"value":"12345"}\n', max_line_bytes=8)
    with pytest.raises(NDJSONError, match="input"):
        parse_ndjson('{"a":1}\n{"b":2}\n', max_total_bytes=8)


def test_ndjson_rejects_invalid_utf8() -> None:
    with pytest.raises(NDJSONError):
        parse_ndjson(b'{"value":"\xff"}\n')


def test_safe_join_stays_below_base(tmp_path: Path) -> None:
    base = tmp_path / "sandbox"
    base.mkdir()
    assert safe_join(base, "results/output.dat") == (base / "results/output.dat").resolve()
    for value in ("..", "../outside", "nested/../../outside", "C:\\Windows\\system.ini", "/etc/passwd"):
        with pytest.raises(PathPolicyError):
            safe_join(base, value)


@pytest.mark.parametrize(
    "value",
    [
        r"\\server\share\secret.txt",
        r"//server/share/secret.txt",
        r"\\?\C:\secret.txt",
        r"\\.\PhysicalDrive0",
        r"C:relative-but-drive-qualified.txt",
    ],
)
def test_safe_join_rejects_unc_and_device_paths(tmp_path: Path, value: str) -> None:
    with pytest.raises(PathPolicyError):
        safe_join(tmp_path, value)


def test_safe_join_rejects_symlink_components(tmp_path: Path) -> None:
    base = tmp_path / "sandbox"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    link = base / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable for this test user")
    with pytest.raises(PathPolicyError):
        safe_join(base, "link/escape.txt")


def test_safe_join_rejects_existing_junction_or_reparse_point(tmp_path: Path) -> None:
    """Exercise the Windows junction policy when junction creation is available."""

    if os.name != "nt":
        pytest.skip("junctions are Windows-specific")
    base = tmp_path / "sandbox"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    junction = base / "junction"
    # Creating a junction is intentionally best effort: CI accounts may not
    # have SeCreateSymbolicLinkPrivilege, in which case the symlink test above
    # still covers the same reparse-point policy.
    import subprocess

    result = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("junction creation is unavailable for this test user")
    with pytest.raises(PathPolicyError):
        safe_join(base, "junction/escape.txt")
