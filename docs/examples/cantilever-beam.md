# Cantilever beam — 1D beam model

This represents the centerline with a rectangular beam section and should reach
the reference with far fewer elements than the solid or shell model.

Read the [common definition](cantilever-common.md) first.

Model: [FCStd](../../examples/models/cantilever-beam.FCStd) ·
[STEP](../../examples/models/cantilever-beam.step)

## FreeCAD model and setup

Open the supplied model, or create a 200 mm line named `CantileverBeam` along
global `x`.

- analysis: linear `static`;
- material: `E=210e9 Pa`, `nu=0.3`, `rho=7850 kg/m3`;
- section: `kind="beam_section"`, `section_type="rectangular"`,
  `rect_width_m=0.020`, `rect_height_m=0.004`, targeting the edge;
- rotation: assign it only if inspection shows incorrect native section axes;
- support: fixed at `x=0`, including beam rotations;
- load: `add_remote_load` targeting the free vertex, with
  `reference_point_m=[0.200, 0.0, 0.0]` and `force_n=[0, 0, -10]` N;
- mesh: `element_dimension="1d"`, second order, using 50, 25, and 10 mm.

## Results and acceptance

Compare free-end `z` displacement with `1.190476 mm`; target 2%. A persistent
large discrepancy usually means swapped section axes, incomplete rotational
restraint, or the truss preset. Confirm bending in `x-z` and report whether the
result layout is source 1D or CalculiX-expanded 3D.
