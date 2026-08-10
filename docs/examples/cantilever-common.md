# Common cantilever definition

The solid, shell, and beam examples represent the same prismatic cantilever.

## Parameters

| Quantity | Symbol | Value |
|---|---:|---:|
| Length | `L` | 200 mm |
| Section width | `b` | 20 mm |
| Section height | `h` | 4 mm |
| Young's modulus | `E` | 210 GPa |
| Poisson's ratio | `nu` | 0.30 |
| Density | `rho` | 7850 kg/m3 |
| Total transverse end load | `F` | 10 N |

Use global `x` along the beam, `y` along the width, and `z` along the height.
Clamp `x=0`. Apply the total force in global `-z` with `add_remote_load`, using
a reference point at the center of the free end. This makes the load direction
explicit and avoids relying on an entity's inferred normal.

- solid: a `200 x 20 x 4 mm` volume;
- shell: a `200 x 20 mm` midsurface in `x-y`, with 4 mm thickness;
- beam: a 200 mm line in `x`, with a `20 x 4 mm` rectangular section.

## Linear reference

```text
I = b h^3 / 12
delta_tip = F L^3 / (3 E I)
sigma_root = F L (h/2) / I

I = 1.0666667e-10 m4
delta_tip = 1.190476e-3 m = 1.190476 mm
sigma_root = 3.75e7 Pa = 37.5 MPa
```

Tip displacement is the primary comparison. Maximum FE stress directly at a
fully fixed edge or corner is mesh- and idealization-sensitive.

| Model | Mesh size/order | Tip displacement (mm) | Error (%) | Notes |
|---|---|---:|---:|---|
| Solid | | | | |
| 3D shell | | | | |
| Beam | | | | |

Use `abs(FEA-reference)/reference * 100`. Start with a 5% target and refine any
model that misses it.
