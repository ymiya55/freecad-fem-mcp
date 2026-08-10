# Tool reference

[日本語](tool-reference.ja.md) · [Back to README](../README.md)

The MCP exposes the fixed tools listed below. The live MCP schema is authoritative for required fields, bounds, and return shapes; this page explains when an analyst should use each tool.

There are no CAD modeling tools in this tool set. `open_model` opens existing geometry; it does not create, modify, defeature, or repair geometry.

## Common conventions

- Engineering inputs use SI units unless a field name explicitly says `mm`.
- `document_id` may be omitted for the active document, but explicit IDs are safer when several documents are open.
- `analysis_id` and `job_id` are returned by creation/start calls; reuse them rather than guessing names.
- An entity reference uses the exact FreeCAD object name and subelements:

```json
{
  "object_name": "Cantilever",
  "subelements": ["Face1"]
}
```

- For supported tools, an empty `targets` list means the current FreeCAD GUI selection. Remote conditions and element geometry require explicit targets.
- Model changes are not saved automatically.

## Status and GUI

| Tool | Purpose | Important inputs or notes |
|---|---|---|
| `get_status` | Check bridge, FreeCAD version, and runtime capabilities | Run first; inspect `future_gates` as unavailable features |
| `inspect_document` | Read active document, objects, analyses, and revision | Optional `document_id` |
| `get_selection` | Read the current GUI selection | Use immediately before selection-based changes |
| `set_view` | Change the FreeCAD camera | `front`, `rear`, `left`, `right`, `top`, `bottom`, `isometric`; optional fit |
| `set_visibility` | Show, hide, or isolate FreeCAD tree objects | Exact object names from `inspect_document`; `show`, `hide`, `isolate`, `show_all`, or `hide_all` |
| `capture_gui` | Capture the viewport or full FreeCAD window | Width/height 16–8192; PNG or JPEG |

## Files

| Tool | Purpose | Important inputs or notes |
|---|---|---|
| `open_model` | Open a model inside an allowed root | Absolute bounded path |
| `save_document` | Save to an allowed path | Existing-file overwrite requires `overwrite=true` and matching `expected_revision` |

## Analysis definition

| Tool | Purpose | Important inputs or notes |
|---|---|---|
| `create_analysis` | Create native `SolverCalculiX` analysis | `static`, `frequency`, or `buckling`; nonlinear and increment options apply to static |
| `assign_material` | Assign global or regional material | Pa, kg/m³, optional hardening and yield points |
| `assign_element_geometry` | Define shell/membrane thickness or beam/truss section | Explicit Face targets for shell; Edge targets for beam; dimensions in metres |
| `add_boundary_condition` | Add fixed, displacement, pin, or roller support | Preferred typed support API; rotations only for beam-containing analyses |
| `add_load` | Add force, pressure, gravity, acceleration, or centrifugal load | N, Pa, m/s², or Hz according to field name |
| `add_remote_load` | Add global remote force and/or moment | Explicit coupled region and reference point; N and N·m |
| `add_remote_displacement` | Add global remote translation and/or rotation | Explicit coupled region; metres and radians; `null` means free DOF |
| `add_connection` | Add tie, contact, or cyclic-symmetry connection | Exactly one slave Face and one master Face |
| `add_constraint` | Add coplanarity MPC, coordinate transform, or compatibility constraint | Prefer typed boundary/load tools for new workflows |
| `create_mesh` | Start a native Gmsh mesh job | Element size in mm; first/second order; `1d`, `2d`, or `3d` |
| `validate_analysis` | Run pre-solve checks | Use `strict=true` before every solve |

### `create_analysis` options

- `analysis_type="static"`: optional `geometrical_nonlinearity`, `material_nonlinearity`, automatic incrementation, four time values, and maximum increments.
- `analysis_type="frequency"`: `eigenmodes_count` and optional paired low/high frequency bounds.
- `analysis_type="buckling"`: `buckling_factors` and `buckling_accuracy`.

If explicit time values are used, initial, minimum, maximum, and period values must all be supplied and satisfy `minimum ≤ initial ≤ maximum ≤ period`.

### `assign_element_geometry` variants

- `kind="shell"`: `thickness_m`, optional `offset`, and `formulation="shell"|"membrane"`.
- `kind="beam_section"`: `rectangular`, `circular`, `pipe`, `elliptical`, `box`, or `truss`, with only the dimensions required by that section.
- `kind="beam_rotation"`: `rotation_rad` for explicit beam Edges.

### Boundary conditions

- `fixed`: all applicable degrees of freedom fixed.
- `displacement`: three nullable translations and, for beams, three nullable rotations. Numeric zero is constrained; `null` is free.
- `pin`: translations fixed, rotations free.
- `roller`: one global translation fixed by `axis` or an axis-aligned unit `normal_m`.

### Loads

- `force`: `force_n` on explicit targets or current selection.
- `pressure`: `pressure_pa` on Faces.
- `gravity` / `acceleration`: exactly three `acceleration_m_s2` components.
- `centrifugal`: `rotation_frequency_hz` and one straight Edge axis; empty targets can mean all elements.

### Connections

- Tie requires `tolerance_m` and `adjust`.
- Contact uses `surface_behavior="hard"|"linear"|"tied"`. Linear/Tied behavior requires positive normal stiffness. Friction additionally requires a coefficient and positive stick stiffness.
- Cyclic symmetry requires tolerance, adjust, `sectors`, and `connected_sectors`, and currently uses the native origin/global +Z axis.

## Jobs

| Tool | Purpose | Important inputs or notes |
|---|---|---|
| `start_analysis` | Start a native CalculiX job | Run only after successful validation |
| `get_job` | Read one mesh or solver job | Poll the returned `job_id` until a terminal state |
| `list_jobs` | List bounded jobs | Optional `analysis_id` filter |
| `cancel_job` | Cancel queued or running job | Does not remove the analysis definition |

Terminal states should be treated as immutable. If a job fails, correct the reported model or environment problem before starting another job.

## Results

| Tool | Purpose | Important inputs or notes |
|---|---|---|
| `get_results` | Retrieve bounded numerical results | `displacement`, `stress`, `strain`, `von_mises`; `max_items` up to 10,000 |
| `show_result` | Display a result field in FreeCAD | Static `frame` or frequency/buckling `mode` |

Static pipeline frames are zero-based. Frequency and buckling modes are one-based. A nonzero static frame and a mode cannot be requested together. Reaction is not a supported public result field.

## Recommended call order

```text
get_status
→ inspect_document
→ create_analysis
→ assign_material
→ assign_element_geometry (1D/2D when needed)
→ add_boundary_condition / add_load / add_connection
→ create_mesh → get_job
→ validate_analysis
→ start_analysis → get_job
→ get_results → show_result → set_visibility (optional) → capture_gui
→ save_document (optional)
```
