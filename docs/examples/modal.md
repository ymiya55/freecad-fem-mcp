# Cantilever modal analysis

This verifies the first bending frequency using the same analytical comparison
as the repository's native FreeCAD acceptance benchmark.

Model: [FCStd](../../examples/models/modal.FCStd) ·
[STEP](../../examples/models/modal.step)

## Model

Open the supplied model, or use a `100 x 10 x 10 mm` solid fixed at one end,
with `E=210 GPa`, `nu=0.3`,
and `rho=7850 kg/m3`. Create `analysis_type="frequency"` with at least six
modes and no static load. Use a second-order 3D mesh at 5 and 2.5 mm.

## Reference and acceptance

```text
f1 = beta1^2 / (2 pi L^2) * sqrt(E I / (rho A))
beta1 = 1.8751040687
A = b h
I = b h^3 / 12

f1 = 835.52 Hz for the stated dimensions and material
```

Request and display each mode. Identify bending, torsion, and axial shapes from
deformation rather than order alone. The two first transverse bending modes
should be nearly degenerate for the square section. Target 5% agreement with
`835.52 Hz` and
reduced change after refinement.

Executable check: `tests/freecad_modal_buckling_benchmark.py`.
