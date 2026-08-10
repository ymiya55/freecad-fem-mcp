# Cantilever beam — 3D shell model

This uses a bending-capable shell in three-dimensional space. It is not a
plane-stress continuum and it is not a membrane.

Read the [common definition](cantilever-common.md) first.

Model: [FCStd](../../examples/models/cantilever-shell.FCStd) ·
[STEP](../../examples/models/cantilever-shell.step)

## FreeCAD model and setup

Open the supplied model, or create a `200 x 20 mm` face named
`CantileverShell` in global `x-y`. The face is the midsurface; the physical
height is supplied as shell thickness.

- analysis: linear `static`;
- material: `E=210e9 Pa`, `nu=0.3`, `rho=7850 kg/m3`;
- geometry: `kind="shell"`, `formulation="shell"`,
  `thickness_m=0.004`, `offset=0.0`, targeting the face;
- support: fixed on the `x=0` edge;
- load: `add_remote_load` targeting the `x=L` edge, reference point at the edge
  midpoint, and `force_n=[0, 0, -10]` N;
- mesh: `element_dimension="2d"`, second order, using 10, 5, and 2.5 mm.

```text
formulation="shell"    -> *SHELL SECTION, bending retained
formulation="membrane" -> *MEMBRANE SECTION, bending removed
```

Do not substitute the membrane formulation; this load requires bending.
For a surface starting at the origin, the reference point is
`[0.200, 0.010, 0.0] m`.

## Results and acceptance

Compare free-edge `z` displacement with `1.190476 mm` and target 5% agreement.
Confirm that the source result is 2D even if CalculiX also supplies expanded 3D
output. Use displacement as the primary cross-idealization result because shell
and solid stress recovery differ.
