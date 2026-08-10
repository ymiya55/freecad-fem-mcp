# Cantilever beam — solid model

This is the recommended “Hello World” analysis: solid geometry, material,
support, load, 3D mesh, linear solution, and displacement display.

Read the [common definition](cantilever-common.md) first.

Model: [FCStd](../../examples/models/cantilever-solid.FCStd) ·
[STEP](../../examples/models/cantilever-solid.step)

## FreeCAD model and setup

Open the supplied FCStd model, or create one `200 x 20 x 4 mm` box named
`CantileverSolid`. Confirm the final face identifiers by inspection.

- analysis: linear `static`;
- material: `E=210e9 Pa`, `nu=0.3`, `rho=7850 kg/m3`;
- support: fixed on the `x=0` face;
- load: `add_remote_load` on the `x=L` face, with the reference point at the
  face center and `force_n=[0, 0, -10]` N;
- mesh: `element_dimension="3d"`, second order, using 8, 4, and 2 mm.

The reference point is `[0.200, 0.010, 0.002] m` if the box starts at the
global origin. Verify that it matches the actual geometry. Validate before
solving.

## Results and acceptance

1. Confirm a smooth first-bending deformation.
2. Compare free-end `z` displacement with `1.190476 mm`.
3. Confirm opposite bending-stress signs across the section height away from
   the fixed corner.
4. Record all mesh levels. The last change should be smaller than the first.

The refined result should normally be within 5% of beam theory. Do not use the
largest stress at the fixed edge as the convergence metric.
