# H3 ordinary rmsh semantic translator milestone — 2026-09-09

Implemented in the existing live `D:\HaloRE\GitHub\Foundry-Fast` checkout on
`feature/h3-scenario-inspection`. Starting HEAD was
`d790066ace27fa5bc4e49251f16f9182b557764c`, clean and 32 commits ahead of the
tracked branch. It differed from the supplied handoff HEAD
`896fba134b0ebbba79e7180cde5b66e90be1e18e`. No reset, checkout, remote sync,
rebase, clean, push, lighting bake or production tag regeneration was performed.
The milestone commit containing this report is the ending HEAD; obtain its full
SHA with `git log -1 --format=%H -- docs/h3-rmsh-semantic-translation.md`.

The named ZIP was absent. Its extracted five specified files were present in
`D:\HaloRE\ForCodex`; their bytes were copied unchanged into the regression
fixture directory and compared before committing. No shader theory was
re-derived and no shader-name exceptions were introduced.

`H3 decoder snapshot -> frozen H3MaterialRecord -> pure translate() -> frozen
ReachAuthoringPlan -> ReachStager -> ShaderTag / native completion` is now the
production path. The source adapter retains the complete raw record, RMDF,
category indices/names, authored and default provenance, function bytes,
externs, bitmap identity/index, sampler, UV/channel metadata and supplied hashes.
All nested mappings/sequences are frozen copies. A plan is bound to the source
record hash. Derived values never feed back into source state.

Plans separate parameters, field origins and compatibility inputs, with
versioned rule IDs, BRDF status, overall translation status and diagnostics.
All four requested rules use the supplied equations. The two directional
power/roughness functions remain independent; the single-lobe normalization
is gated to single-lobe. Ordinary direct category/parameter lanes are bounded
explicitly, including the existing supported renderer externs and unit detail
normal behavior. Other controls require rules. Diffuse-only and none do not
receive generic specular controls.

The writer selects the plan's explicit options and validates native RMOP
declarations; rejected selections cannot keep a node-group default. It maps
angle-color to both Foundry endpoint controls and the exponent, and writes the
native TwoColor/Exponent function with a readback check. Native completion uses
the same authoring receipt instead of writing the fields a second time.
The normal ShaderTag export entry consumes the saved plan too, so exporting a
staged material outside the environment worker cannot bypass the contract.
Rejected semantic writes disable the base Tag context's save-on-exception
behavior. Existing targets are not unlinked in the semantic completion path.

Historical name matching and approximate native contracts remain isolated as
legacy preview behavior for regression callers. `ReachStager(legacy_preview=True)`
is an explicit opt-in; legacy staged materials are refused by native export
until restaged semantically. Existing preview smoke assertions remain intact.

The actual saved Voi closure matches the supplied plan identity
`ce4bc7703b93302eff0f1b60c07be9afe03bfb124a525a7be683cb708ccc5bf4`.
The census enumerates each shader once and retains use counts, render/collision
triangle counts and BSP metadata.

| Selected rule | Materials |
| --- | ---: |
| `h3.two_lobe_phong_to_reach.two_lobe_phong.canonical_v1` | 140 |
| `h3.single_lobe_phong_to_reach.two_lobe_phong.v1` | 12 |
| `h3.diffuse_only_to_reach.diffuse_only.v1` | 38 |
| `h3.none_to_reach.none.v1` | 1 |
| `UNRESOLVED_REQUIRES_RULE` | 26 |

BRDF rules are selected for 191 materials. Overall source-field/function
translation is `TRANSLATED` for 47 (12 single-lobe, 34 diffuse-only, 1 none)
and unresolved for 170. All 140 real two-lobe records retain an unresolved
`analytical_anti_shadow_control`, which the old prototype omitted. Four
diffuse-only records have nonconstant functions; other function blockers remain
reported on their materials as well. Rule selection is not writer acceptance.

The unsupported family count is 11 Cook-Torrance, 7 terrain, 6 ordinary foliage
material models, 1 specialized foliage/default and 1 glass. Organism, halogram,
MCC PBR and other unproven families also fail closed. There is no time-zero
staticization of nonconstant or input-driven functions in this translator.

`glancing_roughness` is calculated and retained separately as a required
compatibility input. The existing generic `_setup_parameter` can allocate
arbitrary parameter elements, but the ordinary writer resolves selected RMOP
declarations and provides no verified migration-version/save/postprocess
contract for this hidden value. Therefore the writer reports
`UNRESOLVED_WRITER_COMPATIBILITY`, including when the value is missing from a
two-lobe plan. It does not substitute a visible socket or claim tag acceptance.
This remains a writer integration limitation, separate from the passing 140
canonical BRDF vectors.

The complete angle-color function is implemented through the existing native
FunctionEditor API, preserving normal -> color 0, glancing -> color 1 and the
exponent. Its pure writer/readback tests use an editor double. Blender smoke
uses real bundled nodes but synthetic RMOP declarations. No live ManagedBlam
tag save/reopen, Tool/Faux run or engine rendering was performed. The 47
otherwise resolved materials remain `NOT_VALIDATED` at the native writer;
missing native declarations will block rather than drop fields. The supplied
asphalt fixture's historical runtime validation is not a new runtime test.

Run the non-destructive census from the checkout in PowerShell, using a new
output directory on each invocation:

```powershell
python tools\census_h3_material_translation.py `
  --manifest D:\HaloRE\PortCensus\voi_full_scenario_20260908\plan-01\materials\shader_manifest.json `
  --plan D:\HaloRE\PortCensus\voi_full_scenario_20260908\plan-01\environment.plan.json `
  --output D:\HaloRE\PortCensus\semantic-material-translation-review-next
```

Reviewed output is in
`D:\HaloRE\PortCensus\semantic-material-translation-20260909-reviewed\materials.json`
and `materials.md`. The command reads saved JSON only and refuses existing
output directories and output under tag/data trees. Earlier development outputs
remain in `semantic-material-translation-20260909-01` and
`semantic-material-translation-20260909-final`, each containing the same two
report filenames. The source JSON files were never rewritten.

| Evidence file | SHA-256 |
| --- | --- |
| Saved `environment.plan.json` bytes | `d28bbf9bdf67e92fda1e076e6e58b74f78703e28ed61cd3ebd1c3b7e5cda6266` |
| Original `shader_manifest.json` bytes | `cc60fa4ff0dfa5fb0c4ad53149aeaf0d245c013711b446b88b1effcdb04baf94` |
| Reviewed `materials.json` | `4d650b597c771a828b05f2f165406058bc064010a347cc21a1c840d6e2ceccfc` |
| Reviewed `materials.md` | `e3f5df1ca95e9ffc761a4dc66e336f7d0aaac2896ab12d0247b9e64b4fb3128e` |

| Validation | Passed | Failed |
| --- | ---: | ---: |
| Pure translator/writer/census unit suite | 181 | 0 |
| Existing H3 import suite | 171 | 0 |
| Existing H3 environment suite | 159 | 0 |
| Blender 5.2.1 material smoke script | 1 | 0 |

The 181 include all 12 single-lobe and 140 two-lobe vectors, 7 selected fixtures
and 22 contract tests. The selected 7 were run first. The existing 55 material
tests were also run separately before the full 171 import suite; these are
subsets, not additional unique tests. Total: 511 distinct unit tests plus one
Blender smoke process. Syntax compilation and `git diff --check` also passed.
The workflow now includes the new pure suite; hosted CI was not run.

```powershell
python -m unittest discover -s tests -p test_h3_material_translation.py
python -m unittest discover -s tests -p 'test_h3_import*.py'
python -m unittest discover -s tests -p 'test_h3_environment*.py'
& 'C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe' --background --factory-startup --python-exit-code 1 --python tests\blender_h3_reach_smoke.py
```

Complete repository file inventory, relative to the live checkout:

| Change | File |
| --- | --- |
| New | `blender/addons/io_scene_foundry/h3_import/material_translation.py` |
| New | `blender/addons/io_scene_foundry/h3_import/material_writer.py` |
| New | `blender/addons/io_scene_foundry/h3_import/material_census.py` |
| Modified | `blender/addons/io_scene_foundry/h3_import/reach_builder.py` |
| Modified | `blender/addons/io_scene_foundry/h3_import/port_environment/worker.py` |
| Modified | `blender/addons/io_scene_foundry/h3_import/port_environment/native_materials.py` |
| Modified | `blender/addons/io_scene_foundry/h3_import/port_environment/native_contracts.py` |
| Modified | `blender/addons/io_scene_foundry/managed_blam/shader.py` |
| New | `tools/census_h3_material_translation.py` |
| New | `tests/test_h3_material_translation.py` |
| Modified | `tests/blender_h3_reach_smoke.py` |
| Modified | `.github/workflows/h3-scenario-inspection-test.yml` |
| New | `tests/fixtures/h3_rmsh_translation/h3_reach_rmsh_translation_spec_v1_2026-09-09.md` |
| New | `tests/fixtures/h3_rmsh_translation/voi_material_census_2026-09-09.json` |
| New | `tests/fixtures/h3_rmsh_translation/voi_single_lobe_regression_vectors_2026-09-09.json` |
| New | `tests/fixtures/h3_rmsh_translation/voi_two_lobe_selected_fixtures_2026-09-09.json` |
| New | `tests/fixtures/h3_rmsh_translation/voi_two_lobe_regression_vectors_2026-09-09.json` |
| New | `docs/h3-rmsh-semantic-translation.md` |

No files under either H3EK or HREK were written. The production Voi scenario,
textures and lighting remain outside this milestone. Review the implementation
and resolve the reported writer/field boundaries before clean regeneration.
