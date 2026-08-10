# Geometrically nonlinear cantilever

This demonstrates large rotation with a linear elastic material by comparing
linear geometry with `geometrical_nonlinearity="nonlinear"`.

Model: [FCStd](../../examples/models/large-deformation.FCStd) ·
[STEP](../../examples/models/large-deformation.step)

## Model and procedure

Open the supplied model, or create a `1000 x 20 x 10 mm` solid cantilever. Use
`E=210 GPa`, `nu=0.3`, a
fixed end, and a `100 N` transverse end force applied with `add_remote_load` at
the free-face center, using a global transverse force vector. Use second-order
3D elements and automatic incrementation. Suggested unit-period controls are: initial `0.05`,
minimum `1e-4`, maximum `0.1`, and at least 100 increments. These are static
solver controls, not physical seconds.

1. Compare linear and nonlinear solutions at a small load; they should agree.
2. Run the 100 N linear-geometry case.
3. Run nonlinear geometry with a force amplitude ramped from zero to full load.
4. Repeat with a finer mesh and smaller maximum increment.
5. Compare final displacement and deformation path. Large rotation is not
   expected to follow the small-deflection beam equation.

## Acceptance

The job reaches full load, history is smooth, refinement stabilizes the final
result, and the small-load nonlinear solution approaches the linear solution.
Report displacement relative to beam length.

This workflow case should later be locked to a suitable official CalculiX
nonlinear test after its native FreeCAD representation is matched exactly.
