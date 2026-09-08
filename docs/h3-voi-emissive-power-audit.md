# Voi material Lightmap Power audit

This is a bounded diagnostic of existing native environment lighting, following
the [generic-light power comparison](h3-voi-lighting-audit.md). Material Lightmap
Power and a placed light's intensity are separate inputs. Prototype 1.9.49's
runtime-accepted geometry, collision, ladders, glass, materials and sunlight stay
the baseline. The accepted H3 source plan is unchanged.

The completed first Power25 bake cannot establish causality: Nate intentionally
edited two fixture shaders while it was running. Those edits are preserved, and
the run is marked `INVALIDATED_CONCURRENT_USER_SHADER_EDITS`. A fresh Low
baseline and material-only comparison with the edited shaders held constant are
in progress. No conversion multiplier has been approved.

## Actual authoring path

[C20's H3 material documentation](https://c20.reclaimers.net/h3/source-data/h3-materials/)
describes `lp` as emitted-light scaling. The
[Reach parameter inventory](https://c20.reclaimers.net/hr/guides/json-parameters/)
lists material `lighting_emissive_power` separately from placed-light
`light_intensity`. The implementation trace is:

1. Halo Material Properties, Lightmap Properties, Power edits
   `material.nwo.material_props[emissive].material_lighting_emissive_power`.
   The property lives in `props/mesh.py`; the UI is in `ui/panel/__init__.py`.
2. `export/virtual_geometry.py:gather_face_props` passes material color and power
   through `utils.get_light_final_color_and_intensity`. With normalized color,
   power stays unchanged. HDR color can fold its maximum component into power.
3. The exporter emits per-triangle float32
   `bungie_lighting_emissive_power` GR2 annotations. Whole-mesh properties also
   have an extended-data path. The sidecar names the GR2; it does not contain
   material power rows itself.
4. Reach Tool's native `scenario_structure_lighting_info` contains `material
   info.emissive power`. BSP material `imported material index` links the
   rendered shader/triangles to that row. The same material identity is present
   in the generated Faux data.

The actual Blender 5.2.1 RNA/export smoke compares 3.2 and 25 on one synthetic
face, with a second unmodified face. Only the selected power annotation changes;
color, attenuation and the other face remain identical. The Voi experiment edits
the existing Tool-compiled terminal field directly, with complete XML readback.
It does not reimport geometry or claim a second GR2/Tool authoring round trip.

`native_scene.render_properties` retains source material power and converts the
color into Blender's linear representation. Its inverse attenuation adapter
cancels Foundry's scene/authoring unit conversion on export. In this fixture,
native attenuation remains 1/2 world units; this is not evidence for multiplying
all H3 distances by 100. `native_scene.write_static_lights` preserves the Tool
material rows. Shader `self_illum_intensity` is a separate runtime appearance
parameter and is not this material-lightmapper field.

## Source, GR2 and native accounting

`tools/read_gr2_material_lighting.py` reads actual exported triangle annotations.
`tools/audit_environment_emission.py` joins source identities, native readback,
GR2 material variants and Faux material indices. It accounts for all **12
positive native rows representing 14 H3 material slots**:

| BSP | Native row | H3 material slots | Shader/variant | Power | Falloff / cutoff |
| --- | ---: | --- | --- | ---: | --- |
| 000 | 1 | 58 | out_light_box | 10 | 1 / 4 |
| 000 | 2 | 23 | tech | 1 | 10 / 20 |
| 000 | 3 | 117 | warm | 3.2 | 1 / 2 |
| 000 | 4 | 71 | cool blue | 8 | 1 / 2 |
| 000 | 5 | 95, 100 | cool blue | 3.2 | 1 / 2 |
| 000 | 6 | 143 | warm | 3.2 | 1 / 2 |
| 010 | 1 | 43, 103 | tech | 1 | 10 / 20 |
| 010 | 2 | 94 | cool white, directional approximation | 0.8 | 1 / 2 |
| 010 | 3 | 84 | cool blue | 3.2 | 1 / 2 |
| 010 | 4 | 86 | warm | 3.2 | 1 / 2 |
| 010 | 5 | 87 | warm | 3.2 | 1 / 2 |
| 010 | 6 | 82 | cool white | 3.2 | 1 / 2 |

Exact shader paths, source lighting indices, colors, focus, quality, flags,
bounce ratios, GR2 meshes, native material slots and hashes are in the JSON
audit. The selected diagnostic changes only BSP010 native rows 2, 3 and 6 to 25.
It leaves all generic lights, warm-material rows, geometry, sky, shader appearance
and other material-lighting fields unchanged.

Read-only x64 inspection of the installed `tool_fast.exe` independently finds a
surface-emitter construction path that reads positive material power/color,
groups triangles, and passes power, focus, attenuation and bounce into an emitter.
The per-unit flag introduces an area calculation; the unflagged branch passes
power directly. These observations are tied to the captured executable hash and
instruction listings. They demonstrate an engine path, not cache invalidation
or equivalent H3/Reach photometry.

## Controlled comparison and preservation

Both runs use the same installed Low preset, all selected BSPs, one worker, and
normal Foundry `faux_data_sync`/farm stages. Complete native XML comparisons
allow only the selected material powers to differ before and after Faux. The
accepted plan and output manifest are pinned. Actual bitmap `processed pixel
data` is compared, because tag-header hashes can change without pixel changes.
The FP32 array reader also records changed local texels and 32-by-32 tile counts;
it does not map atlas coordinates to world positions or reconstruct radiance.

The first completed but invalidated test changed 30,718 BSP010 payload bytes;
BSP000 payloads and reported photon totals were identical. This is retained as
an observation, not attributed to material power, because two shaders changed
during that run. The restoration guard stopped before overwriting either shader.
After Nate confirmed ownership, only the 13 diagnostic lighting files were
restored. Both edited shaders remain hash-pinned, read-only external inputs to
the fresh pair and are excluded from compiler ownership.

Direct reads of the captured shader files verify changed `self_illum_intensity`
values and shader options. Tool XML exports of files outside the kit resolved
through the current logical tag identity and were unsuitable for comparing the
captured originals; those exports are explicitly marked invalid evidence. The
read-only `compare_shader_semantics` helper avoids that ambiguity.

The local evidence root is
`D:\HaloRE\PortCensus\voi_emissive_input_audit_20260907`. Key artifacts:

- `emissive-source-gr2-native-audit-02.json`: complete 12-row accounting.
- `material-power-rna-export-02.json`: actual Blender material export test.
- `material-power25-low-02/`: completed but invalidated experiment, captured
  user edits, native XML, payload deltas and guarded recovery receipt.
- `edited-shaders-baseline-low-01/`: fresh baseline with the user shaders.
- `user-edit-preservation-parent.json`: ownership boundary for those edits.

## Manual bake runner

Nate's pasted manual bake failed because it requested H3 BSP `040_bsp_000`.
The generated Reach BSPs are `factory_a_env_bsp_0000` and
`factory_a_env_bsp_0001`. The empty job's `TASK SUCCEEDED` message did not mean a
valid environment bake; its farm later failed. The local
`D:\HaloRE\scripts\Bake-FactoryA-Low.ps1` now validates the actual native BSP
files and defaults to `all`. Its original is backed up in the evidence root.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'D:\HaloRE\scripts\Bake-FactoryA-Low.ps1' -ValidateOnly
```

Validation writes no tags and starts no bake. The manual runner rejects an
already-running Foundry/Faux bake. It uses the stock local farm driver and is
not the one-worker comparison path used for the controlled experiment.
