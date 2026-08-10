# Troubleshooting

[日本語](troubleshooting.ja.md) · [Back to README](../README.md)

Start with the symptom that you see. Do not copy or publish the contents of `%LOCALAPPDATA%\freecad-fem-mcp\bridge-v1.json`; it contains a short-lived authentication token.

## Installation check fails

Run:

```powershell
.\scripts\check.ps1 -SkipMcpConfig
```

If the Addon is missing or does not point to this repository, reinstall it:

```powershell
.\scripts\install.ps1 -SkipMcpConfig
```

Restart FreeCAD after reinstalling. If the destination already contains an Addon not managed by this installer, inspect and back it up before deciding whether `-Force` is appropriate.

## The MCP client does not show `freecad-fem` tools

1. Confirm that `uv sync` completed.
2. Confirm that the MCP registration uses an absolute repository path.
3. For Codex, run `codex mcp get freecad-fem`.
4. Restart the MCP client or start a new task.
5. Check that the configured command runs `uv run --project <repository> freecad-fem-mcp`.

The server uses STDIO. Do not add messages to its stdout or wrap the command in a script that prints banners.

## `get_status` cannot connect to FreeCAD

Check the following in order:

1. FreeCAD `>=1.1.3,<1.2` is running with a GUI.
2. The Addon is present at `%APPDATA%\FreeCAD\v1-1\Mod\FreeCADFEMMCP`.
3. FreeCAD was restarted after the latest Addon installation.
4. Only one intended FreeCAD GUI process is running.
5. The MCP client was restarted after registration.

The last FreeCAD process that starts the bridge owns the connection record. Running `FreeCADCmd` for a benchmark can temporarily replace it. Restart the intended FreeCAD GUI and start a fresh MCP-client task afterward.

## Bridge authentication is not configured

This usually means that no live FreeCAD bridge record is available, or that a previous FreeCAD process exited. Restart the intended FreeCAD GUI. Do not manually copy the token into environment variables or logs.

## The wrong FreeCAD document is being modified

- Keep one FreeCAD GUI process open during an MCP workflow.
- Run `inspect_document` before each major setup stage.
- Pass the returned `document_id` when multiple documents are open.
- Confirm the analysis ID before adding material, loads, or supports.

## A selected face or edge is rejected

Run `get_selection` immediately before the modifying request. Common causes are:

- nothing is selected;
- the selected entity type is wrong, such as an Edge where a Face is required;
- the geometry changed and the old `FaceN` or `EdgeN` reference is stale;
- the same entity appears more than once;
- the request uses a label or `object_id` instead of the exact `object_name`.

Re-select the entity in the current FreeCAD GUI and retry. For explicit references, use this shape:

```json
{
  "object_name": "Cantilever",
  "subelements": ["Face1"]
}
```

## Meshing fails

Verify:

- Gmsh is configured and works from the FreeCAD FEM workbench;
- `element_dimension` matches the model: `1d`, `2d`, or `3d`;
- beam sections are assigned to the required Edges;
- shell thickness is assigned to the required Faces;
- the mesh size is positive and appropriate for the geometry;
- the selected shape is valid and visible to the analysis.

Use `get_job` to read the bounded job status and diagnostic summary. Do not retry repeatedly without correcting the reported cause.

## `validate_analysis` fails

Validation is intended to stop an incomplete or inconsistent model before CalculiX starts. Typical findings include:

- missing material, density, support, load, mesh, beam section, or shell thickness;
- rigid-body motion or duplicate constraints;
- overlapping or incomplete regional material assignments;
- unsupported pressure on a membrane model;
- invalid contact pair or contact property combination;
- frequency analysis without density;
- buckling analysis without support or preload.

Correct the model and run validation again. Do not ask the assistant to bypass validation with raw INP or Python; those paths are intentionally unavailable.

## The solver job fails or does not finish

Use `get_job` with the returned job ID. If the job remains active and must be stopped, use `cancel_job`. Then check:

- CalculiX configuration in FreeCAD;
- the preceding strict validation result;
- material and section units;
- contact stiffness and friction values;
- nonlinear increment ordering and maximum increments;
- available disk space in the FreeCAD working directory.

Job logs are size-limited and sanitized. For a native FreeCAD or CalculiX failure that is not explained by the MCP summary, reproduce it in a disposable model through the FreeCAD FEM GUI.

## Results are empty or a mode is rejected

- Wait until the solver job is `completed`.
- Confirm the requested field is one of `displacement`, `stress`, `strain`, or `von_mises`.
- For frequency and buckling, use a one-based `mode` that was actually solved.
- For static results, use the pipeline `frame`; do not combine a mode with a nonzero frame.
- Reaction is not a public result field in the verified FreeCAD 1.1.3 path.

For beam and shell results, inspect `result_layout`. FreeCAD may display an expanded 3D result even though the source analysis is 1D or 2D.

## `open_model` or `save_document` rejects a path

Use an absolute path inside a configured allowed root. The policy rejects path traversal, UNC paths, device paths, alternate data streams, disallowed extensions, and escapes through reparse points.

For a first analysis, open the model manually in FreeCAD. To overwrite an existing file, supply both `overwrite=true` and the current `expected_revision` returned by document inspection.

## Collecting a safe problem report

Include:

- FreeCAD, Python, Gmsh, and CalculiX versions;
- the output of `check.ps1 -SkipMcpConfig`;
- the failed MCP tool name and sanitized error message;
- analysis type and model dimension;
- the smallest reproducible model that contains no confidential data.

Never include the bridge token, the full connection record, private model paths, or proprietary geometry unless you explicitly intend to share them.
