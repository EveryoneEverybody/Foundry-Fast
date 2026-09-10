# Voi material Lightmap Power audit

This is a bounded diagnostic of existing native environment lighting, following
the [generic-light power comparison](h3-voi-lighting-audit.md). Material Lightmap
Power and a placed light's intensity are separate inputs. Prototype 1.9.49's
runtime-accepted geometry, collision, ladders, glass, materials and sunlight stay
the baseline. The accepted H3 source plan is unchanged.

The clean Power25 comparison changed **55,322 bytes of BSP010 lightmap pixel
data**. BSP000's three bitmap payloads stayed byte-identical; photon totals also
stayed identical. Material Lightmap Power therefore affects this bake path, and
the earlier generic-light intensity test does not establish its behavior.
The fresh baseline was restored exactly, including Nate's two intentional
fixture-shader edits. No conversion multiplier was applied permanently.

The first completed Power25 bake remains
`INVALIDATED_CONCURRENT_USER_SHADER_EDITS`: those shaders changed during it.
The valid comparison used a newly baked baseline with both edits held constant.
That baseline completed before the PC restart; the subsequent diagnostic and
preservation checks completed after it.

## Actual authoring path

[C20's H3 material documentation](https://c20.reclaimers.net/h3/source-data/h3-materials/)
describes `lp` as emitted-light scaling. The
local Foundry writers expose material `lighting_emissive_power` separately
from placed-light `light_intensity`. The material path below is verified from
Foundry code and the actual exported/native data; C20's Reach JSON inventory
does not enumerate these emissive material fields. The implementation trace is:

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

This establishes power/value transport, not complete lighting equivalence.
The refined audit reports `VALUE_MATCH_WITH_SEMANTIC_REVIEW_REQUIRED`: ten
positive native rows originate from H3 rows whose `use attenuation` bit is off,
but Foundry exports enabled attenuation with their stored distances. Only
BSP000 row 1 and BSP010 row 2 originate from explicitly enabled H3 attenuation.
In particular, tested source slots 82/84 have the flag off; slot 94 has it on.
Fresh schema reads of BSP010 agree with the preserved snapshot's flags.

The pinned H3 schema names bit zero `use attenuation`; Reach calls the same
bit `reserved{use attenuation}`. `native_scene.render_properties` currently
uses H3 flags for per-unit emission but ignores attenuation enablement.
`gather_face_props` writes `bungie_lighting_attenuation_enabled=1` for positive
emission. Equal stored falloff/cutoff numbers therefore do not establish the
intended source range. This difference is now an explicit machine-readable
warning, with focused synthetic tests.

Foundry's cutoff property describes zero as using realistic falloff/cutoff, but
this is authoring guidance, not proof that directly zeroing the native table
has the same effect. Read-only Tool inspection finds import setters storing the
authoring values and a later surface-emitter constructor reading native range
values. The target's disabled/default-range derivation still needs verification
through the actual import behavior or its complete engine path. No zero-range,
100-times-distance, reserved-bit, or power multiplier correction is applied.

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

The clean pair used BSP010 source material slots 82, 84 and 94, which map to
native material rows 6, 3 and 2. Their baseline powers were 3.2, 3.2 and 0.8;
each diagnostic power was 25. Native XML readback before and after Faux permits
only those three power changes. All 13 Faux stages exited zero in each run,
as did both diagnostic XML exports. Baseline and diagnostic bake times were
1,937.742 and 1,936.843 seconds respectively.

| Pixel payload | BSP000 changed bytes | BSP010 changed bytes |
| --- | ---: | ---: |
| FP32 lightmap array | 0 | 50,157 |
| VMF direction | 0 | 37 |
| VMF intensity | 0 | 5,128 |
| Total | **0** | **55,322** |

The nine BSP010 FP32 planes contain respectively 1,230, 1,214, 1,233, 1,262,
1,268, 1,232, 1,188, 1,255 and 1,204 changed texels: **11,086 across planes**.
There are no changed nonfinite channel pairs. These are atlas/plane counts,
not unique world-space surface samples or a measurement of tunnel brightness.

| BSP | Baseline photons | Power25 photons | Accumulated photon energy, both runs |
| --- | ---: | ---: | ---: |
| 000 | 1,225,359 | 1,225,359 | 186.655807 |
| 010 | 270,428 | 270,428 | 2.704280 |

Identical photon totals do not mean identical final lighting: the pixel
comparison demonstrates a response to the changed material input. An additional
sun control is unnecessary to establish this response. This does not verify
every generic-light/cache path, H3/Reach photometric parity, or a visually fixed
tunnel. No new runtime acceptance is claimed.

Automatic restoration returned all **986 tracked output/external files** to
the fresh baseline exactly: 980 compiler-owned files and six preserved external
files, including both user shaders. Independent final checks also verified all
50 proof-box files and the accepted source-plan hash. Geometry and generic-light
fields were unchanged. Captured diagnostic lighting remains in the evidence
directory; the installed level uses the baseline.

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

- `emissive-source-gr2-native-audit-04.json`: complete 12-row accounting with
  the ten attenuation-enablement warnings; supersedes the value-only audit.
- `material-power-rna-export-02.json`: actual Blender material export test.
- `material-power25-low-02/`: completed but invalidated experiment, captured
  user edits, native XML, payload deltas and guarded recovery receipt.
- `edited-shaders-baseline-low-01/`: fresh baseline with the user shaders.
- `edited-shaders-power25-low-01/`: valid material-only comparison, native XML,
  before/after captures, local texel deltas and exact restoration receipt.
- `emissive-diagnostic-outcome.json`: consolidated result with evidence hashes.
- `final-preservation-verification.json`: independent final preservation checks.
- `validation-checkpoint-03.json`: completed local validation, including the
  previously observed Windows bitmap-worker failure and passing isolated retry.
- `user-edit-preservation-parent.json`: ownership boundary for those edits.
- `emissive-attenuation-enablement-observation.json`: source flags, retained
  ranges and exact unverified target behavior.

The controlled diagnostic command is:

```powershell
& 'C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe' --background --factory-startup --python 'D:\HaloRE\GitHub\Foundry-Fast\blender\addons\io_scene_foundry\h3_import\port_environment\runtime_bake.py' -- 'D:\HaloRE\PortCensus\voi_emissive_input_audit_20260907\edited-shaders-power25-low-config-01.json'
```

This is a record of the completed invocation, not a request to rerun it. A
deliberate repeat needs a copied configuration with a new run directory and
matching baseline hashes; completed evidence directories must not be overwritten.

## Checkpoint validation

The diagnostic machinery and shader-preservation changes were committed locally
as `13bf5e88d9a0d6770ff05b22f39c6ddfaf57bf75` on
`feature/h3-scenario-inspection`. The subsequent checkpoint adds this completed
result and the attenuation-enablement audit warning, without changing converter
behavior. Local validation:

- 157 environment tests passed, including proof-box regressions and the two
  new attenuation-audit cases.
- 38 pure test modules are covered across isolated runs. The unchanged bitmap
  worker module first encountered a Windows `PermissionError` on `result.json`;
  all 25 of its tests passed in the isolated post-restart retry. This is not
  reported as a clean single-pass suite.
- Rust: 102 passed, one asset-dependent test ignored.
- Blender 5.2.1 environment smoke and actual material RNA/export smoke passed.
- Hosted CI was not run. No normal release/feed was published.

The remaining semantic question is how normal Reach authoring should express
H3's disabled emissive attenuation and derive the native default range. The
source flag, current exporter behavior and native field consumers are recorded;
the missing target behavior is explicit. Neither Power25 nor an arbitrary range
multiplier is a source-grounded converter fix.

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
