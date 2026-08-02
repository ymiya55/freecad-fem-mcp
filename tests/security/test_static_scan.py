from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.security_scan import scan_file


def test_static_scan_detects_forbidden_constructs(tmp_path: Path) -> None:
    sample = tmp_path / "unsafe.py"
    sample.write_text(
        """\nresult = eval(user_input)\nsubprocess.run(command, shell=True)\nserver.bind(('0.0.0.0', 8000))\n""",
        encoding="utf-8",
    )
    rules = {finding.rule for finding in scan_file(sample, tmp_path)}
    assert {"python-eval-exec", "shell-true", "non-loopback-bind"} <= rules


def test_static_scan_detects_secret_shapes(tmp_path: Path) -> None:
    sample = tmp_path / "secrets.env"
    sample.write_text("AWS=AKIA1234567890ABCDEF\n", encoding="utf-8")
    findings = scan_file(sample, tmp_path)
    rules = {finding.rule for finding in findings}
    assert "aws-access-key" in rules
    assert all("AKIA" not in finding.snippet for finding in findings)


def test_static_scan_allows_official_freecad_validation_helpers(tmp_path: Path) -> None:
    sample = tmp_path / "official.py"
    sample.write_text(
        "import femtools.checksanalysis\nimport femtools.membertools\n",
        encoding="utf-8",
    )
    assert not [finding for finding in scan_file(sample, tmp_path) if finding.rule == "legacy-solver-import"]


def test_static_scan_rejects_legacy_solver_execution_symbols(tmp_path: Path) -> None:
    sample = tmp_path / "legacy.py"
    sample.write_text(
        "from femtools.ccxtools import CcxTools\nmakeSolverCalculiXCcxTools()\n",
        encoding="utf-8",
    )
    rules = {finding.rule for finding in scan_file(sample, tmp_path)}
    assert "legacy-solver-import" in rules
