# Your first analysis

[日本語](first-analysis.ja.md) · [Back to README](../README.md)

This guided analysis is the FreeCAD FEM MCP equivalent of “Hello World.” You will solve a steel cantilever under a uniform transverse pressure, review displacement and stress, and keep the model unsaved until you approve it.

The rectangular beam is created manually in FreeCAD because this MCP provides FEM analysis operations, not CAD modeling operations.

## Engineering objective

Determine the deformation and stress pattern of a rectangular cantilever:

| Item | Value |
|---|---|
| Length | 100 mm |
| Width | 10 mm |
| Height | 10 mm |
| Young's modulus | 210 GPa |
| Poisson's ratio | 0.30 |
| Density | 7,850 kg/m³ |
| Support | One end face fixed |
| Load | 0.1 MPa pressure on the top face |
| Mesh | 5 mm, first-order 3D |

The expected behavior is downward bending, maximum displacement at the free end, and maximum bending stress near the fixed end. Elementary beam theory gives a useful order-of-magnitude reference of approximately `0.071 mm` free-end displacement and `30 MPa` maximum bending stress. A coarse 3D mesh and the precise pressure application will cause some difference.

## Before you start

Complete [Setup](setup.md). Start one FreeCAD GUI process and use a fresh Codex or MCP-client task.

In FreeCAD:

1. Create a new document.
2. Switch to the Part workbench.
3. Create a Box with `Length = 100 mm`, `Width = 10 mm`, and `Height = 10 mm`.
4. Rename the object to `Cantilever`.
5. Fit the model in the 3D view.

Saving is optional. This workflow operates on the active document and does not save automatically.

## 1. Check the connection and model

Send this prompt:

```text
Use only the freecad-fem MCP. Run get_status and inspect_document.
Confirm that FreeCAD is connected and that the active document contains
one solid object named Cantilever. Do not change the document yet.
```

Do not continue until the response reports a connected bridge and the expected solid.

## 2. Create the analysis and material

Send:

```text
Use only the freecad-fem MCP. Create a linear static SolverCalculiX analysis
for the active document. Assign a global isotropic steel material with
Young's modulus 210e9 Pa, Poisson's ratio 0.30, and density 7850 kg/m^3.
Report the analysis ID and stop before adding supports or loads.
```

Keep the returned analysis ID in the same conversation.

## 3. Fix one end

In the FreeCAD 3D view, select the `10 mm × 10 mm` end face at the start of the beam. Then send:

```text
Use get_selection to verify that exactly one Face of Cantilever is selected.
Using the current GUI selection, add a fixed boundary condition to the
analysis created above. Stop if the selection is empty or is not one Face.
```

Check that a fixed-support object appears in the FreeCAD model tree.

## 4. Apply the pressure

Clear the selection and select the long `100 mm × 10 mm` top face. Then send:

```text
Use get_selection to verify that exactly one Face of Cantilever is selected.
Using the current GUI selection, apply a pressure of 100000 Pa to the analysis.
Stop if the selection is empty or is not the top Face.
```

Positive FreeCAD pressure acts toward the selected surface. Inspect the load symbol before solving.

## 5. Mesh, validate, and solve

Send:

```text
Create a first-order 3D Gmsh mesh with a 5 mm element size for the analysis.
Poll the mesh job with get_job until it finishes. If meshing succeeds, run
validate_analysis in strict mode and report every warning or error.
Only if validation succeeds, start CalculiX and poll the solver job until it
finishes. Stop immediately if any job fails.
```

Validation should confirm that the model has material, support, load, and mesh assignments before CalculiX starts.

## 6. Review the results

Send:

```text
For the completed analysis, get the displacement and von_mises results.
Report the maximum values and their units. Show the displacement result in
FreeCAD, set an isometric view, fit the model, and capture the viewport.
Do not save the document.
```

Review these engineering checks:

- The free end should have the largest displacement.
- The displacement direction should match the applied pressure.
- The highest bending stress should occur near the fixed end.
- The result should be finite and broadly consistent with the beam-theory reference.
- A coarse-mesh stress peak should not be treated as a converged design value.

## 7. Save only after review

If the setup and results are acceptable, ask the client to call `save_document`. Saving to a new path requires an allowed root. Overwriting an existing file additionally requires explicit `overwrite=true` and the current document revision.

## What you have exercised

This workflow uses the complete analysis path:

```text
FreeCAD model → inspection → analysis → material → support → load
→ Gmsh mesh → validation → CalculiX solve → numerical result → GUI contour
```

For routine projects, continue with [Daily workflow](daily-workflow.md). For other analysis types, see [Capabilities](capabilities.md).
