# H3 illumination preview

Version 1.9.28 connects `illum_detail` in the Blender material preview. The fusion-coil report selected `constant_color`, `material_model=none`, `self_illumination=illum_detail`, and `blend_mode=additive`. The previous preview left both illumination textures unconnected and displayed a white Principled surface.

`illum_detail` multiplies the RGB values of `self_illum_map`, `self_illum_detail_map`, `DETAIL_MULTIPLIER` (4.59479), `self_illum_color`, and `self_illum_intensity`. Each texture retains its own transform and sampler. This HLSL function returns RGB without multiplying by texture or tint alpha, despite the option help text describing alpha masking.

Unlit object materials with supported illumination, no environment mapping, and no alpha test use an Emission shader. Opaque materials use that emission directly. Additive materials add a white Transparent BSDF so the background remains visible without a white diffuse surface. Other material models and blend combinations keep their previous approximate surface and diagnostics.

The imported values remain decoder samples at zero. Object `health` inputs, scrolling, Halo exposure, fog, bloom, pass sorting, and Reach shader-tag generation are not implemented by this change. `off` no longer produces a misleading unsupported self-illumination warning.

## Source

Verified against `halohlsl/Halo3-Shader-Source` commit `257ca5f9e1149a31dbfb6a7c9141bd232f590e5b`:

- `hlsl/self_illumination.fx`, `calc_self_illumination_detail_ps`
- `hlsl/albedo.fx`, `DETAIL_MULTIPLIER`
- `hlsl/material_model_none.fx`, `calc_material_none_ps`
- `hlsl/blend.fx`, additive output policy

## Checks

The synthetic fixture uses the fusion-coil options and sampled tint/intensity, not Halo image data. Tests cover active texture links, separate transforms, zero-alpha RGB, additive background transmission, material identity, image reuse, missing-texture diagnostics, unchanged lit surfaces, and packed images after saving. Numerical Cycles and Eevee renders check emission over a known background and zero-intensity transparency. These are not real H3EK appearance or Reach Tool tests.

## Remote repository

`Build and deploy Foundry extension` (`static.yml`) now builds and tests Windows helpers when the selected source contains the H3 bridge, pins packaging to the same source commit, and verifies that the helpers are present in the extension before generating the Pages index. Non-H3 sources skip helper compilation. Running the test workflow alone still does not publish Pages.
