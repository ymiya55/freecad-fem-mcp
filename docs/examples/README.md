# Structural analysis examples

This directory is the CAE-oriented entry point to FreeCAD FEM MCP. Each example
describes the engineering model, MCP workflow, reference solution, and checks
that make a result credible. Users do not write CalculiX input files.

Ready-to-open FCStd files and neutral STEP copies are stored in
[`examples/models`](../../examples/models/README.md). Prefer FCStd because it
also contains subelement hints and avoids STEP import renumbering.

## Example matrix

| Example | Idealization | Analysis | Verification | MCP status |
|---|---|---|---|---|
| [Cantilever: solid](cantilever-solid.md) | 3D continuum | Linear static | Beam-theory tip displacement | Available |
| [Cantilever: 3D shell](cantilever-shell.md) | Shell in 3D space | Linear static | Same cantilever reference | Available |
| [Cantilever: beam](cantilever-beam.md) | 1D beam | Linear static | Same cantilever reference | Available |
| [Large-deformation cantilever](large-deformation.md) | 3D continuum | Nonlinear static | Increment and mesh convergence | Available |
| [Frictionless contact](contact.md) | 3D continuum pair | Nonlinear contact | Force balance and penetration | Available |
| [Cantilever modes](modal.md) | 3D continuum | Modal | First bending frequency | Available |
| [Euler column](linear-buckling.md) | 3D continuum | Linear buckling | Euler critical load | Available |

The first three examples intentionally use the same dimensions, material, and
load. They are different finite-element idealizations, not three names for the
same element.

## Common MCP workflow

1. Create the geometry in FreeCAD and save an `.FCStd` file under an allowed
   root. MCP configures and solves existing geometry; it does not provide
   general-purpose CAD creation tools.
2. Open the file and call `inspect_document` and `get_selection`. Confirm all
   `FaceN`, `EdgeN`, and `VertexN` references instead of guessing them.
3. Create the requested analysis and assign SI material data.
4. For shells and beams, call `assign_element_geometry`. A solid needs no
   section assignment.
5. Add supports and loads, create the Gmsh mesh, and wait for the mesh job.
6. Run `validate_analysis` with `strict=true`. Resolve every diagnostic.
7. Start the analysis, wait for the job, and inspect values with `get_results`
   before displaying them with `show_result`.
8. Record mesh size, element order, result quantity and location, reference
   value, relative error, and solver warnings.

Suggested request to an MCP client:

> Open `<absolute path to model.FCStd>`. Inspect the model and identify the
> named support and load entities. Set up the analysis described in this
> example using SI inputs. Validate before solving. Report every mesh setting,
> solver warning, measured result, reference value, and relative error. Do not
> guess a FaceN or EdgeN identifier.

## CalculiX relationship

The CalculiX project ships solver-level decks and reference results in its
[official test suite](https://github.com/Dhondtguido/CalculiX/tree/master/test).
These examples reuse suitable problem classes and verification principles, but
FreeCAD FEM MCP generates the deck through FreeCAD's native writer. It does not
import or rewrite arbitrary `.inp` files. Differences in geometry, mesh, load
application, and result recovery must therefore be documented.

## Interpretation rules

- A smaller mesh size is not proof of correctness. Check model definition,
  reactions, deformation shape, and a reference quantity.
- Peak stress at a fixed corner, point load, or contact edge may be singular.
- A 2D surface mesh does not by itself mean plane stress. This MCP uses its 2D
  path for shell or membrane elements.
- CalculiX may expand shell and beam output to 3D. That does not make the source
  mesh a solid mesh.
