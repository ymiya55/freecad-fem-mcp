# Daily workflow

[日本語](daily-workflow.ja.md) · [Back to README](../README.md)

This workflow keeps the AI assistant, the active FreeCAD document, and the analyst's engineering decisions synchronized.

## Start the session

1. Start one FreeCAD GUI process.
2. Prepare the geometry manually in FreeCAD or with a separate modeling tool/MCP. Then open the intended model manually, or use `open_model` for a path inside an allowed root.
3. Start a fresh MCP-client task.
4. Run `get_status` and `inspect_document` before making changes.
5. Record the active `document_id`, document revision, geometry objects, and intended analysis type.

Use a short opening request:

```text
Use only the freecad-fem MCP. Check status and inspect the active document.
Summarize the model objects, existing analyses, and current revision.
Do not modify or save anything.
```

## Define the engineering intent first

Before tool calls, state:

- analysis type and model dimension;
- material model and units;
- support idealization;
- load definitions and coordinate system;
- connection assumptions;
- mesh size/order and any local refinement intent;
- requested result quantities;
- validation or benchmark target.

Ask the assistant to repeat the setup in a compact table. Resolve ambiguous faces, signs, units, and reference points before changing the model.

## Build the analysis in checkpoints

### Checkpoint 1: analysis and material

Create the analysis, assign material, and inspect the document again. For frequency analysis, confirm density. For nonlinear material behavior, confirm the hardening model and every yield point in SI units.

### Checkpoint 2: element idealization

For 1D and 2D models, assign every required beam section, beam rotation, shell thickness, formulation, and regional material before meshing. Confirm that no Edge or Face region is unassigned or duplicated.

### Checkpoint 3: supports and loads

Use `get_selection` immediately before applying GUI-selection-based conditions. After each condition, verify the object created in the FreeCAD tree and the direction shown in the viewport.

Prefer `add_boundary_condition` and `add_load` over the compatibility forms in `add_constraint`. Use explicit targets for remote conditions and connections.

### Checkpoint 4: mesh

Start `create_mesh`, retain the returned job ID, and use `get_job` until the job reaches a terminal state. Inspect the mesh in FreeCAD before solving:

- correct 1D/2D/3D idealization;
- adequate element size near stress gradients;
- expected second-order setting;
- no missing bodies or regions;
- plausible element count and aspect ratios.

### Checkpoint 5: validation

Run `validate_analysis(strict=true)`. Treat every error as a stop condition. Review warnings as engineering decisions rather than asking the assistant to suppress them.

### Checkpoint 6: solve

Start `start_analysis` only after validation succeeds. Poll the returned job with `get_job`; do not issue duplicate solves while the job is queued or running. Use `cancel_job` when an active job is no longer valid.

## Review results

Retrieve only the fields needed for the decision. Check:

- units and deformation scale;
- displacement direction and constrained degrees of freedom;
- stress location and whether a peak is caused by a singularity;
- mode ordering and physical mode shape;
- buckling preload and sign;
- source dimensionality for expanded beam/shell results;
- consistency with hand calculations, prior runs, or a benchmark.

Use `show_result` and `capture_gui` for traceable visual review. Before a report capture,
use `inspect_document` to obtain exact object names and `set_visibility` with `isolate`
to leave only the mesh or result pipeline visible. Use `show_all` to restore all
GUI-visible tree objects afterward. A screenshot is evidence of display state, not
proof of mesh convergence or model validity.

## Save and close

The MCP never saves automatically. Before `save_document`:

1. inspect the document and review the current revision;
2. confirm the intended file path;
3. decide whether an existing file may be overwritten;
4. retain the model, assumptions, solver version, and result review together.

For exploratory work, save to a new file rather than overwriting the starting model.

## Recommended prompt pattern

```text
Use only the freecad-fem MCP.

Objective: [engineering question]
Model: [active document and dimension]
Material: [SI properties]
Supports: [entities and constrained DOFs]
Loads: [entities, values, signs, coordinate system]
Mesh: [dimension, size, order]
Results: [requested fields or modes]

Work in checkpoints. Inspect selections before using them, validate before
solving, wait for every job, and stop on any error. Do not save unless I
explicitly approve the final model.
```

For the first end-to-end run, use [Your first analysis](first-analysis.md).
