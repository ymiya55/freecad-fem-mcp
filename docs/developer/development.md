# Development guide

[Back to README](../../README.md)

## Repository layout

```text
src/freecad_fem_mcp/       STDIO MCP server
addon/FreeCADFEMMCP/       FreeCAD Addon
security/                  dependency-free security policy
scripts/                   Windows install, check, uninstall, and security tools
tests/                     unit, contract, security, native, and benchmark tests
docs/                      analyst and developer documentation
```

## Development environment

```powershell
uv sync --frozen --extra dev
uv run --frozen --extra dev pytest
```

The Addon must remain importable in FreeCAD 1.1.3's bundled Python without third-party packages. Protocol and policy tests that do not require FreeCAD should remain runnable under the normal project Python.

## Design invariants

- Call FreeCAD APIs only from the Addon.
- Perform FreeCAD document operations only on the Qt GUI thread.
- Wrap modifying operations in FreeCAD undo transactions.
- Use native FreeCAD `GmshTools` and `CalculiXTools`, not assembled process commands.
- Reserve STDOUT for the MCP protocol; send diagnostics to STDERR.
- Keep public MCP tools and bridge method/action pairs allowlisted and closed.
- Reject unknown and non-finite inputs before dispatch.
- Do not add arbitrary execution, unrestricted file access, raw INP, or legacy solver symbols.
- Update user documentation whenever tools, units, FreeCAD versions, or supported engineering combinations change.

## Standard checks

```powershell
uv run --frozen --extra dev pytest
uv run --frozen --extra dev ruff check .
uv run --frozen --extra dev bandit -c .bandit -r src addon security scripts
uv run --frozen --extra dev pip-audit --local --skip-editable
uv run --frozen python scripts/security_scan.py
.\scripts\run_security_tests.ps1 -Python ".\.venv\Scripts\python.exe"
```

## FreeCAD integration tests

Set the tested FreeCAD executable directory, then run the required scripts with `FreeCADCmd.exe`. Typical entry points include:

```powershell
$freecadRoot = Join-Path $env:LOCALAPPDATA "Programs\FreeCAD 1.1\bin"
& (Join-Path $freecadRoot "FreeCADCmd.exe") ".\tests\freecad_integration.py"
& (Join-Path $freecadRoot "FreeCADCmd.exe") ".\tests\freecad_accuracy_benchmark.py"
& (Join-Path $freecadRoot "FreeCADCmd.exe") ".\tests\freecad_modal_buckling_benchmark.py"
```

Additional native probes and beam/shell benchmarks in `tests/` must be selected according to the feature being changed.

## End-to-end acceptance

A public FEM capability should be tested through this path:

1. Install or stage the Addon.
2. Start the FreeCAD GUI and authenticated bridge.
3. Open a disposable fixture.
4. Create native analysis, solver, material, element geometry, supports, loads, and connections through MCP routes.
5. Complete a native Gmsh job and verify a non-empty mesh.
6. Pass strict native CalculiX validation.
7. Complete a native CalculiX job and result import.
8. Retrieve finite numerical results.
9. Display and capture the relevant GUI result.
10. Verify rejection paths leave the document revision unchanged.

Quantitative features require an analytical or trusted numerical benchmark with an explicit tolerance. GUI success alone is not an accuracy test.

## Documentation

The English README and English analyst pages are the default public documentation. Keep their Japanese counterparts semantically aligned for the bilingual pages. Developer documentation is maintained in English.
