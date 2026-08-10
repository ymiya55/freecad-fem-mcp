# Frictionless compression contact

This checks nonlinear face-to-face contact without mixed solid-shell pairs.

Model: [FCStd](../../examples/models/contact.FCStd) ·
[STEP](../../examples/models/contact.step)

## Model and setup

Open the supplied model, or create two aligned `20 x 20 x 10 mm` solid blocks
in one compound while keeping
them as distinct solids with opposing `20 x 20 mm` faces. Fix the lower block's
bottom. Apply `1000 N` downward to the upper top with `add_remote_load`, using a
reference point at that face center and `force_n=[0, 0, -1000]` N.
Start with coincident opposing faces; safe initial-gap control is not currently
exposed.

Use `E=210 GPa`, `nu=0.3`, a second-order 3D mesh of the compound, and geometric nonlinearity.
Set the lower opposing face as master and upper as slave. Add
`connection_type="contact"`, `surface_behavior="hard"`, `friction=false`.

## Checks and acceptance

1. Validate distinct, opposing slave and master faces.
2. Confirm convergence to full load and physically consistent downward motion.
3. Check 1000 N reaction balance if native reaction output is available; if it
   is unavailable, report that instead of inferring it from a contour.
4. Refine contact faces and compare displacement, pressure, and penetration.

Artificial penetration must not increase under refinement. Contact-edge peak
pressure is mesh-sensitive; prefer integrated force and central pressure. This
uses the native writer and is conceptually aligned with CalculiX contact tests,
not a bit-for-bit reproduction of a test deck.
