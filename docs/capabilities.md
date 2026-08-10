# Capabilities

[日本語](capabilities.ja.md) · [Back to README](../README.md)

FreeCAD FEM MCP automates bounded workflows that FreeCAD 1.1 can represent with native FEM objects, Gmsh, and `SolverCalculiX`. It is intended for traceable engineering workflows, not unrestricted FreeCAD or CalculiX scripting.

## Analysis scope, not modeling

The MCP does not create or edit CAD geometry. Before an FEM workflow starts, the analyst must provide geometry in one of these ways:

- create or edit it manually in FreeCAD;
- open an existing `FCStd` model;
- import prepared CAD geometry into FreeCAD; or
- use a separate modeling tool or MCP, then hand the resulting FreeCAD document to this MCP.

This MCP can inspect existing objects and their Faces or Edges, but its creation tools are limited to FEM objects such as analyses, materials, element properties, supports, loads, connections, meshes, and results.

## Analysis types

| Analysis | Supported scope | Main outputs |
|---|---|---|
| Linear static | Single-step structural analysis | Displacement, stress, strain, von Mises stress |
| Nonlinear static | Single-step geometric and/or material nonlinearity with bounded time increments | Structural results and bounded convergence summary when present in native output |
| Natural frequency | Requested number of modes with optional frequency range | Natural frequency and mode shape by one-based mode number |
| Linear buckling | Requested number of buckling factors and solver accuracy | Buckling factor and mode shape by one-based mode number |

Frequency analysis requires density. Buckling analysis requires a valid support and preload. Use `validate_analysis` before every solve.

## Model dimensionality

| Model | Native definition |
|---|---|
| 3D solid | Solid geometry meshed through the native 3D Gmsh path |
| 2D shell | Explicit Face references, thickness, offset, and bending-capable shell formulation |
| 2D membrane | Explicit Face references, thickness, offset, and in-plane membrane formulation |
| 1D beam | Explicit Edge references with rectangular, circular, pipe, elliptical, or box section and optional section rotation |
| 1D truss | Explicit Edge references with area and bending stiffness excluded |

The mesh dimension must be selected explicitly for 1D and 2D analyses. Beam/truss and shell/membrane definitions share a solver element model and cannot be mixed ambiguously in one analysis. A 3D-expanded beam or shell result remains identified as originating from a 1D or 2D model.

## Materials

Supported material data use SI units:

- Young's modulus in Pa
- Poisson's ratio as a dimensionless value
- density in kg/m³
- optional yield strength in Pa
- isotropic or kinematic hardening
- 1 to 64 stress/plastic-strain yield points for material nonlinearity

A material can be global or assigned to explicit Edge, Face, or Solid regions. Validation rejects overlapping regions, ambiguous global/region mixtures, stale references, and incomplete regional assignments.

## Supports and kinematic conditions

- Fixed support
- Prescribed translation
- Prescribed rotation for analyses containing 1D beams
- Pin support: three translations fixed, rotations free
- Cartesian roller: one global translational degree of freedom fixed
- Remote translation and rotation coupled through a global reference point
- Rectangular or cylindrical nodal coordinate transform
- Native CalculiX `*MPC,PLANE` coplanarity condition

The coplanarity MPC keeps referenced nodes in a movable plane. It is not a frictionless support, fixed symmetry plane, or antisymmetry support.

## Loads and amplitudes

- Concentrated or distributed force through native FreeCAD force objects
- Surface pressure
- Gravity or arbitrary acceleration vector
- Centrifugal load about one explicit straight Edge axis
- Remote global force and moment
- Bounded tabular amplitude for supported force, pressure, prescribed displacement, and remote conditions

Amplitude tables contain 2 to 256 time/scale points. Time starts at zero and increases strictly; scale is dimensionless. Independent load cases, arbitrary CalculiX step text, and multiple analysis steps are not exposed.

## Connections

| Connection | Current scope |
|---|---|
| Tie | One slave Face and one master Face, with tolerance and adjust |
| Contact | Static, non-thermal contact with Hard, Linear, or Tied normal behavior; optional bounded friction and stiffness |
| Cyclic symmetry | Native tie with sector counts, using the FreeCAD native origin and global +Z axis |

Shell-to-shell tie/contact uses the same API. Mixed shell/solid pairs, thermal contact, initial-gap controls, penetration controls, automatic contact pairing, arbitrary native properties, and custom cyclic-axis placement are not supported.

## Meshing and solving

- Native FreeCAD `GmshTools`
- First- or second-order mesh request
- Explicit 1D, 2D, or 3D path
- Native FreeCAD `CalculiXTools`
- Asynchronous mesh and solver jobs with status, listing, and cancellation
- Official FreeCAD/CalculiX pre-solve validation

The Addon does not construct raw Gmsh or CalculiX shell commands.

## Results and visualization

- Bounded numerical retrieval for displacement, stress, strain, and von Mises stress
- Static result selection by pipeline frame
- Frequency and buckling result selection by one-based mode number
- FreeCAD GUI result display
- Front, rear, left, right, top, bottom, and isometric views
- Bounded show, hide, isolate, show-all, and hide-all control for named FreeCAD tree objects
- Viewport or FreeCAD-window capture as PNG or JPEG

Reaction force is not public because the verified FreeCAD 1.1.3 native result object does not provide the required reaction array. The MCP does not invent zeros or parse unrestricted output to fill the gap.

## File and document behavior

- Work with an already-open FreeCAD document without file-path configuration
- Open or save models only inside configured allowed roots
- Explicit save only; no automatic save after analysis changes
- Existing-file overwrite requires `overwrite=true` and a matching document revision
- Model changes participate in FreeCAD undo transactions

## Current exclusions

The current release does not provide:

- CAD geometry creation, editing, defeaturing, or repair;
- thermal, thermal-structural, electromagnetic, or electrostatic analysis
- independent load cases, load combinations, envelopes, or multiple analysis steps
- bolt pretension, concentrated mass/rotary inertia, dampers, or connector releases
- general frictionless/symmetry/antisymmetry supports
- arbitrary Python, shell commands, CalculiX INP fragments, or unrestricted file reads
- legacy `SolverCcxTools` or `femtools.ccxtools`

`get_status` is the runtime authority for version-specific capabilities and `future_gates`. A feature listed under `future_gates` is explicitly unavailable, not partially supported.
