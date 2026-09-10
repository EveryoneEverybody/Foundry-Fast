# H3 ordinary rmsh semantic translation — native writer integration, 2026-09-09

Integrated in the existing live Foundry-Fast checkout, starting at
`64783a55cb22815fdfda9f67da5c3c85c1510cda`, with a clean working tree on
`feature/h3-scenario-inspection` (33 commits ahead of its tracked branch).
This report belongs to the subsequent local integration commit; obtain its SHA
with `git log -1 --format=%H -- docs/h3-rmsh-semantic-translation.md`.
No reset, clean, checkout, sync, rebase or push occurred. Production Voi, existing
generated shaders, H3 tags and lighting were not modified or regenerated.

## Production contract

The existing architecture remains:
`H3 decoder -> frozen H3MaterialRecord -> pure translate() -> frozen
ReachAuthoringPlan -> ReachStager -> ShaderTag / native completion`.
Source identity, RMDF, category indices/names, effective values, authored/default
provenance, function bytes/state, externs, bitmap identity/index, sampler, UV,
channel metadata and hashes remain in the immutable source. Plans retain the
source-record hash, explicit options, parameters, origins and compatibility inputs.

The translator continues to use the supplied single-lobe and two-lobe equations.
No BRDF equations, regression fixture values or shader-name exceptions were added.
Both independent directional power/roughness functions are unchanged. Only
single-lobe receives the analytical roughness^4*pi^2 normalization.

The native writer now consumes semantic `glancing_roughness` using:

```text
H3 glancing_specular_power
-> recovered power_to_roughness migration
-> plan.compatibility_inputs.glancing_roughness
-> max(0.0, 0.272909999 * max(glancing_roughness, 0.01)^-1.3973)
-> native hidden glancing_specular_power
```

`native_parameters()` derives this final value without modifying the plan.
Its authoring receipt records the semantic input and the versioned compatibility
rule `reach.glancing_roughness_to_glancing_specular_power.v1`. Native completion
uses that receipt for save/reopen verification; it does not fold SC or area again.

The destination must explicitly be Reach two_lobe_phong, the roughness must be a
static finite scalar in [0,1], and the selected native RMOP must declare
`glancing_specular_power`. Missing declarations, a missing compatibility input,
an invalid value, unknown compatibility state or a competing authored power fail
closed. Socket names do not establish the native contract. Staging validates
after reading selected RMOP declarations. ShaderTag validates against its actual
definition's selected RMOPs before clearing or writing parameters. Rejected
semantic exports still disable Tag's save-on-exception behavior.

The complete `specular_color_by_angle` remains a native TwoColor/Exponent
function: normal tint is color 0, glancing tint is color 1, with the source
exponent and amplitude range 0..1. Incomplete endpoints/exponent or an RGB
snapshot fail closed. Foundry endpoint/socket aliases remain at the writer
boundary. Legacy name matching remains explicit preview-only behavior.

## Anti-shadow loss

The actual Reach two-lobe RMOP has no corresponding
`analytical_anti_shadow_control` field. Reach's renderer/shadow response replaces
this H3 renderer-specific workaround. This is a lossy target-renderer substitution,
not an exact numeric migration.

The translator reuses the established `OPTIONAL_MVP_OMISSION` classification
from `native_contracts.unexposed_parameter`. Diagnostics and field provenance
retain the original H3 value, target-renderer disposition and explicit fidelity
loss. No fake Reach parameter is emitted. This classification alone does not
block static two-lobe authoring; nonconstant or extern-driven functions still do.
Of the 140 two-lobe source records, **35 have nonzero anti-shadow values**.

## Native evidence

The first disposable probe selected static
`levels/solo/040_voi/shaders/metals/metal_pipe_rusty.shader`, with H3 normal and
glancing powers 10, environment mapping none and self-illumination off.

| Quantity | Planned | Real save/reopen |
| --- | ---: | ---: |
| Semantic glancing roughness | 0.19419219303059315 | Retained in plan |
| Current Reach compatibility power | 2.695089554282771 | 2.69508957862854 |

Actual RMOP:
`shaders/shader_options/material_two_lobe_phong_option.render_method_option`.
It declares `glancing_specular_power` with an empty UI name. ManagedBlam accepted
the hidden field. Full angle-color persisted with normal
[0.5647059082984924, 0.3686274588108063, 0.2980392277240753, 1],
glancing [1, 1, 1, 1], exponent 5, master Exponent and graph TwoColor.
Evidence: `D:/HaloRE/PortCensus/rmsh_native_probe_20260909-01/result.json`.

One additional disposable probe used the **production apply_plan writer** with
static `levels/solo/040_voi/shaders/metals/metal_trim_c.shader` (normal power 20,
glancing power 40). It projected the translated plan onto its scalar and
angle-color controls, leaving bitmap asset work out of this persistence probe.
All 11 written parameter/function checks passed after real ManagedBlam reopen.

| Quantity | Planned | Real save/reopen |
| --- | ---: | ---: |
| Semantic glancing roughness | 0.10333186413247018 | Retained in plan |
| Current Reach compatibility power | 6.507735758199279 | 6.507735729217529 |
| Normal roughness | 0.14165536102041346 | 0.1416553556919098 |

The second angle-color retained normal
[0.772549033164978, 0.772549033164978, 0.772549033164978, 1],
glancing [1, 1, 1, 1], exponent 1, master Exponent and graph TwoColor.
Its anti-shadow source value was 0. Neither native probe needed Tool/Faux.

Disposable second tag:
`D:/SteamLibrary/steamapps/common/HREK/tags/levels/h3_port/rmsh_integration_probe_20260909/metal_trim_c_writer_probe.shader`.
Evidence:
`D:/HaloRE/PortCensus/semantic-native-integration-20260909/probe-02/probe-result.json`.
An initial helper launch stopped before ManagedBlam initialization with
`FileExistsError [WinError 183]` because its dependency directory already
existed. The successful retry used a fresh helper directory; no shader write
was rejected.

This proves native persistence for the generic contract, not engine rendering
fidelity. No runtime rendering, full Voi rebuild or visual tuning was performed.

## Saved 217-material census

The saved environment plan and original shader manifest were read unchanged.
A read-only ManagedBlam capture checked 52 selected option tuples against the
live Reach RMDF/RMOPs, with zero query errors and all tag writes disabled.
The JSON census accepts this declaration snapshot through `--rmop-contracts`;
without it, native compatibility eligibility remains unverified/blocked.
Production writers always query the real selected RMOPs themselves.

| Selected translator rule | Selected | Writer eligible | Unresolved |
| --- | ---: | ---: | ---: |
| h3.two_lobe_phong_to_reach.two_lobe_phong.canonical_v1 | 140 | 136 | 4 |
| h3.single_lobe_phong_to_reach.two_lobe_phong.v1 | 12 | 12 | 0 |
| h3.diffuse_only_to_reach.diffuse_only.v1 | 38 | 34 | 4 |
| h3.none_to_reach.none.v1 | 1 | 1 | 0 |
| Unsupported families | 26 | 0 | 26 |
| Total | 217 | 183 | 34 |

All **136 static two-lobe materials are production-writer eligible** against the
captured declarations. Overall semantic status is TRANSLATED for 183 and
UNRESOLVED_REQUIRES_RULE for 34. BRDF rule status remains 191 translated and
26 unresolved. Zero materials report the former unproven glancing compatibility
blocker; zero treat anti-shadow as a blocking unknown. Reports separate semantic
losses (140 anti-shadow records, 35 nonzero) from unresolved reasons.

The 34 unresolved unique materials comprise 11 Cook-Torrance, 7 terrain,
6 ordinary foliage, 1 specialized foliage/default, 1 glass and 8 materials with
nonconstant functions. The four animated two-lobe materials are:

- `levels/solo/040_voi/shaders/lights/metal_doodad_a_illum_cool.shader`
- `levels/solo/040_voi/shaders/lights/metal_doodad_a_illum_warm.shader`
- `levels/solo/040_voi/shaders/metals/metal_crane_platform.shader`
- `levels/solo/040_voi/shaders/metals/metal_crane_upper.shader`

Each retains its nonconstant self_illum_intensity blocker. Four diffuse-only
materials also remain unresolved: flare_a_red_blinky (self_illum_intensity),
light_sequence_red_a_illum (base_map and self_illum_map), clouds_fog (detail_map
and height_map), and lava (detail_map2). Function field counts overlap within
materials. None are flattened. Unsupported families remain unimplemented.

ELIGIBLE means a translated plan fits the captured native declarations. It does
not assert that all 183 materials were written or rendered, or that every
texture/geometry stage has passed. Each unique shader still appears once with
usage, triangle and BSP metadata.

```powershell
python tools/census_h3_material_translation.py `
  --manifest D:/HaloRE/PortCensus/voi_full_scenario_20260908/plan-01/materials/shader_manifest.json `
  --plan D:/HaloRE/PortCensus/voi_full_scenario_20260908/plan-01/environment.plan.json `
  --rmop-contracts D:/HaloRE/PortCensus/semantic-native-integration-20260909/rmop-contracts.json `
  --output D:/HaloRE/PortCensus/semantic-native-integration-review-next
```

Final reports: `D:/HaloRE/PortCensus/semantic-native-integration-20260909/census-final/materials.json`
and `materials.md`. The command refuses existing output directories and output
inside tag/data trees. `rmop-evidence.json` records the live definition/option
hashes; `capture_contracts.py` is the minimal read-only capture helper.

| Evidence | SHA-256 |
| --- | --- |
| Saved environment.plan.json bytes | d28bbf9bdf67e92fda1e076e6e58b74f78703e28ed61cd3ebd1c3b7e5cda6266 |
| Original shader_manifest.json bytes | cc60fa4ff0dfa5fb0c4ad53149aeaf0d245c013711b446b88b1effcdb04baf94 |
| rmop-contracts.json | 2834456fd953bc443d9b3b80eadbf9bbdd148dd2a5099f8e2e6fe06ae420dfa3 |
| Final materials.json | e1615a9d8d0bcfb3eb5fb72e61c9a5f77b44ebcb232e58f994d551e27e06e4cc |
| Final materials.md | 5af6ace3a9cb0ddd770e4c25064345d44a059a6e3b38700b15b6106025c628f3 |
| Second probe-result.json | 35c858110675d5f6e13455c60af6cfcc51b2f46af63458b88bb81dd75ad13258 |

## Validation and changed files

| Validation | Passed | Failed |
| --- | ---: | ---: |
| Pure translator/writer/census unit suite | 188 | 0 |
| Existing H3 import suite | 171 | 0 |
| Existing H3 environment suite | 159 | 0 |
| Blender 5.2.1 material smoke process | 1 | 0 |
| Additional native production writer probe | 1 (11 readback checks) | 0 |

Total: 518 distinct unit tests plus the Blender smoke and one native probe.
The 188 pure tests retain all 12 single-lobe and 140 two-lobe vectors, 7 selected
fixtures and the previous 22 contracts, with 7 new contracts. Coverage includes
asphalt, source/plan immutability, directional noninverse transforms, SC/area
folding, angle endpoint ordering, no group-default fallback, hidden-power
derivation, invalid/missing contracts, anti-shadow losses and animation blockers.
Blender smoke additionally stages two-lobe with declared hidden-power support
and preserves its full semantic plan across .blend save/reopen.

```powershell
python -m unittest discover -s tests -p test_h3_material_translation.py
python -m unittest discover -s tests -p 'test_h3_import*.py'
python -m unittest discover -s tests -p 'test_h3_environment*.py'
& 'C:/Program Files (x86)/Steam/steamapps/common/Blender/blender.exe' --background --factory-startup --python-exit-code 1 --python tests/blender_h3_reach_smoke.py
```

Repository files modified in this integration:

- `blender/addons/io_scene_foundry/h3_import/material_translation.py`
- `blender/addons/io_scene_foundry/h3_import/material_writer.py`
- `blender/addons/io_scene_foundry/h3_import/material_census.py`
- `blender/addons/io_scene_foundry/h3_import/reach_builder.py`
- `blender/addons/io_scene_foundry/h3_import/port_environment/native_materials.py`
- `blender/addons/io_scene_foundry/managed_blam/shader.py`
- `tests/test_h3_material_translation.py`
- `tests/blender_h3_reach_smoke.py`
- `tools/census_h3_material_translation.py`
- `docs/h3-rmsh-semantic-translation.md`

Regression fixture files are unchanged. Disposable helpers and evidence remain
outside the repository under the report directory above.
