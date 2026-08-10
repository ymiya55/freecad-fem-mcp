# Contributing

Thank you for considering a contribution to FreeCAD FEM MCP.

## Before opening an issue

- Use the bug form for reproducible failures.
- Use the feature form for a proposed public MCP capability.
- Do not report vulnerabilities in a public issue; follow
  [SECURITY.md](SECURITY.md).
- Remove tokens, private model data, user names, and absolute local paths from
  logs, screenshots, FCStd files, and other attachments.

This project targets the FreeCAD 1.1.x `SolverCalculiX` framework only. It does
not accept compatibility paths for the legacy CalculiX solver integration.
Features that write CalculiX input should be based on a verified FreeCAD 1.1.x
native object and native CalculiX writer. If either is unavailable, describe the
feature as a future capability instead of adding an INP or Python escape hatch.

## Development setup

The supported development host is Windows with Python 3.11 or later and
[uv](https://docs.astral.sh/uv/).

```powershell
uv sync --frozen --extra dev
uv run --frozen --extra dev pytest
```

FreeCAD integration work additionally requires FreeCAD 1.1.3 or another
compatible 1.1.x build with Gmsh and CalculiX configured. See the
[development guide](docs/developer/development.md) for the native and GUI
acceptance tests.

## Making a change

1. Keep public MCP tools closed and typed. Do not add arbitrary Python, shell,
   command, INP, property, environment, or filesystem access.
2. Keep FreeCAD API calls in the Addon and on the Qt GUI thread.
3. Wrap document mutations in a FreeCAD Undo transaction and preserve document
   state when validation fails.
4. Add tests at the model, bridge, Addon operation, and security boundary layers
   as appropriate.
5. Update the relevant documentation when changing public tools, units,
   supported versions, result semantics, or safety guarantees.
6. Keep source code, tests, documentation, and fixtures free of developer-local
   absolute paths and credentials.

## Required checks

Run the checks that apply to the change before opening a pull request:

```powershell
uv run --frozen --extra dev pytest
uv run --frozen --extra dev ruff check .
uv run --frozen --extra dev bandit -c .bandit -r src addon security scripts
uv run --frozen --extra dev pip-audit --local --skip-editable
uv run --frozen python scripts/security_scan.py
```

Changes to native FEM behavior should also run the relevant portable
`FreeCADCmd.exe` contract, smoke, or numerical benchmark under `tests/`. GUI
changes should include the MCP and GUI acceptance evidence described in the
[development guide](docs/developer/development.md).

## Pull requests

Keep commits focused and use descriptive commit messages. In the pull request,
state:

- what changed and why;
- the FreeCAD native object and writer used, when applicable;
- the safety boundary impact;
- tests and native/GUI checks performed; and
- known limitations or deferred work.

By contributing, you agree that your contribution is licensed under the MIT
License in [LICENSE](LICENSE).
