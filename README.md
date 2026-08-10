# FreeCAD FEM MCP

[![CI](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/ci.yml)
[![Security checks](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/security.yml/badge.svg)](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/security.yml)
[![CodeQL](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/codeql.yml/badge.svg)](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/codeql.yml)

[日本語](README.ja.md)

FreeCAD FEM MCP lets an AI assistant prepare, solve, and review native FreeCAD FEM analyses through the FreeCAD GUI. It uses FreeCAD 1.1 `SolverCalculiX`, Gmsh, and CalculiX; it does not use the legacy `SolverCcxTools` workflow.

> [!IMPORTANT]
> This is an FEM analysis MCP, not a CAD modeling MCP. The geometry must already exist in the active FreeCAD document or in a model opened from an allowed path. Create and edit geometry manually in FreeCAD, or use a separate modeling tool or MCP before starting the FEM workflow.

## What you can analyze

| Area | Current capability |
|---|---|
| Analysis types | Static, natural frequency, and linear buckling |
| Model dimensions | 3D solid, 2D shell/membrane, and 1D beam/truss |
| Materials | Isotropic linear elasticity; isotropic or kinematic hardening for single-step nonlinear statics |
| Supports | Fixed, prescribed displacement/rotation, pin, roller, and remote displacement |
| Loads | Force, pressure, gravity, acceleration, centrifugal load, remote force, and remote moment |
| Connections | Tie, native contact, cyclic-symmetry tie, and native coplanarity MPC |
| Meshing and solve | Native FreeCAD Gmsh and CalculiX tools |
| Results | Displacement, stress, strain, von Mises stress, frequency modes, and buckling modes |

See [Capabilities](docs/capabilities.md) for the supported combinations, engineering meaning, and current limitations.

## Requirements

- Windows
- FreeCAD `>=1.1.3,<1.2`
- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Gmsh and CalculiX configured in FreeCAD

The verified baseline is FreeCAD 1.1.3, Python 3.11.14, Gmsh 4.15.0, and CalculiX 2.22.

## Quick start with Codex

From PowerShell in the repository directory:

```powershell
uv sync
.\scripts\install.ps1 -SkipMcpConfig
codex mcp add freecad-fem -- uv run --project "$PWD" freecad-fem-mcp
codex mcp get freecad-fem
```

Then:

1. Restart FreeCAD and open an `FCStd` model that contains geometry.
2. Restart Codex or start a new task.
3. Ask Codex to check the connection:

```text
Use only the freecad-fem MCP. Run get_status and inspect_document,
then report the FreeCAD version, active document, and model objects.
Do not use shell commands.
```

Continue with [Your first analysis](docs/first-analysis.md) to solve a guided cantilever model.

For Claude Desktop, installation checks, updates, removal, and a setup that does not use the installer script, see [Setup](docs/setup.md), including [Manual installation](docs/setup.md#manual-installation).

## Typical engineering workflow

1. Open an existing model in FreeCAD.
2. Inspect the document and select model faces or edges in the GUI.
3. Create an analysis and assign SI material properties.
4. Add supports, loads, element geometry, and connections.
5. Create a Gmsh mesh and inspect the completed mesh job.
6. Validate the analysis before solving.
7. Start CalculiX and monitor the solver job.
8. Read numerical results, display a result contour, and optionally isolate the mesh or result object for capture.
9. Save explicitly only after reviewing the model.

See [Daily workflow](docs/daily-workflow.md) ([日本語](docs/daily-workflow.ja.md)) for recommended checkpoints and review practices.

## Documentation

### For analysts

- [Setup](docs/setup.md) · [日本語](docs/setup.ja.md)
- [Structural analysis examples](docs/examples/README.md)
- [Your first analysis](docs/first-analysis.md) · [日本語](docs/first-analysis.ja.md)
- [Capabilities](docs/capabilities.md) · [日本語](docs/capabilities.ja.md)
- [Troubleshooting](docs/troubleshooting.md) · [日本語](docs/troubleshooting.ja.md)
- [Tool reference](docs/tool-reference.md) · [日本語](docs/tool-reference.ja.md)
- [Daily workflow](docs/daily-workflow.md) · [日本語](docs/daily-workflow.ja.md)

### For developers

- [Architecture](docs/developer/architecture.md)
- [Development guide](docs/developer/development.md)
- [Release guide](docs/developer/releasing.md)
- [Security design](docs/developer/security.md)

## Safety model

The MCP exposes a fixed set of typed FEM operations. It does not expose arbitrary Python, shell commands, CalculiX input fragments, dynamic imports, or unrestricted file access. Model changes participate in FreeCAD undo transactions and are not saved automatically. Overwriting an existing file requires explicit confirmation and a matching document revision.

## License

MIT License
