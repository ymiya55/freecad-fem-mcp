# Euler column — linear eigenvalue buckling

This verifies a CalculiX buckling factor against Euler theory. It is not a
nonlinear post-buckling analysis.

Model: [FCStd](../../examples/models/linear-buckling.FCStd) ·
[STEP](../../examples/models/linear-buckling.step)

## Model

Open the supplied model, or use a `100 x 10 x 10 mm` solid cantilever column
with `E=210 GPa`, `nu=0.3`,
and `rho=7850 kg/m3`. Fix one end and apply `1000 N` axial compression at the
free end. The ordinary force follows the end-face normal; inspect its direction
and reverse its sign if needed so it is compressive. Create
`analysis_type="buckling"`, request at least three factors,
set `buckling_accuracy=0.01`, and use a second-order 3D mesh.

## Reference and acceptance

For a fixed-free column, `K=2`:

```text
Pcr = pi^2 E I / (K L)^2 = pi^2 E I / (4 L^2)
lambda_reference = Pcr / Papplied
I = b h^3 / 12

Pcr = 43179.52 N
lambda_reference = 43.1795 for Papplied = 1000 N
```

Confirm compressive preload, display all requested modes, and reject rigid-body
or local load-application artifacts. Compare the first physical factor with the
reference value `43.1795` and repeat on a finer mesh; target 5% agreement.

State that linear eigenvalue buckling omits imperfections, plasticity, contact
changes, and post-buckling response and usually overestimates usable load.

Executable check: `tests/freecad_modal_buckling_benchmark.py`.
