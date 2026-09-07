# Voi Factory A source semantic checkpoint

This checkpoint resolves 259 of the original 262 source-contract records with
14 reusable semantic rules. Three records remain blocking. It is a source plan,
not a native environment build or runtime acceptance result.

The working branch is `feature/h3-scenario-inspection`. The stopped source-planning
work was preserved unchanged in local commit
`022dff1d296d25fd7e2b1865c9115f6de71bc102`, after recording all 22 changed/untracked
files, their hashes and a backup archive, then testing the checkpoint. Its parent
is the published 1.9.48 baseline
`4d35ae05821575f612a99d7e659cfe43d05551bd`. No reset, clean, destructive checkout,
rebase or stash operation was used. Remote metadata was fetched after recording
the working tree. No normal release/feed was published.

## Accounting

The source remains `040_voi.scenario`, authored zone set `intro_faa`, source zone
index 1, BSP mask 3: BSP000 and BSP010. The authored player flag remains
`teleport_factorya_player0`, cutscene flag 19, position
`(-10.2022, -108, -1.49976)`, yaw `99.3396` degrees.

| Original family | Before | Resolved | Blocking |
|---|---:|---:|---:|
| Material functions / externs | 150 | 150 | 0 |
| Compiled render-part categories | 68 | 68 | 0 |
| Unassigned instance collision materials | 29 | 29 | 0 |
| Collision flags | 7 | 6 | 1 |
| Native terrain / foliage | 2 | 2 | 0 |
| Active image forms | 2 | 2 | 0 |
| Emissive frustum / flags | 1 | 0 | 1 |
| Lighting-material relationship | 1 | 1 | 0 |
| Unmatched seam | 1 | 0 | 1 |
| Scenario light volumes | 1 | 1 | 0 |
| **Total** | **262** | **259** | **3** |

The mutually exclusive record totals are 81 `NATIVE_DIRECT`, 81
`NATIVE_TRANSFORM`, 85 `NATIVE_REBUILD`, 10 `STATICIZED_MVP`, 1
`OPTIONAL_MVP_OMISSION`, 1 `RUNTIME_LATER`, and 3 `BLOCKING_UNKNOWN`.
Thus native resolutions total 247; `247 + 10 + 1 + 1 + 3 = 262`.
A record containing several parameter resolutions takes its strongest restriction;
all child decisions and fidelity losses remain visible. There are 92 unique
parameter/function/extern signatures, handled by the shared rules rather than
shader-path exceptions.

`semantic_catalog.json` is the machine-readable rule catalog beside the compiler.
`source-semantic-resolution.json` maps every original diagnostic to its stable ID,
rule, resolution class, evidence, confidence, target authoring contract, fidelity
loss, source tag SHA-256, zone identity and blocking status. The source usage links
identify affected BSP triangles and instance placements in `source-dependencies.json`.
The CI fixture contains only the 262 diagnostic identity hashes, not proprietary
geometry or tag payloads. Missing original IDs and newly observed unknowns both
remain blocking; changing extraction order cannot reduce the gate.

## Rules and source evidence

Most material function records store constants. Those retain the decoded authored
scalar, color, alpha or UV transform directly. Cosmetic UV motion and permitted
emissive modulation use the pinned decoder's source time/input zero, preserving
the source bake inputs. Required emission cannot freeze to zero. Animated opacity,
visibility, cutout thresholds, named runtime providers and unknown curve types
remain blocking. Reach owns its native BRDF and rebuilt reflection externs.

The installed H3/Reach shader source verifies both texture-alpha sampling and
cutoff 0.5. Foliage targets `foundry_reach.shader_foliage` with `from_texture`
alpha testing. Reach has no `back_light` color socket. H3's stock static foliage
entry points declare that parameter without reading it; the source recipe is
retained, and Reach flat foliage diffuse lighting is an explicit fidelity
approximation. Wind freezes to the authored undeformed mesh by disabling amplitude
as well as the timer; timer zero alone would retain phase-dependent displacement.

Terrain targets `foundry_reach.shader_terrain` / `ShaderTerrainTag`, retaining all
four source layers, RGBA blend channels, layer order, base/detail/bump bindings,
per-sampler transforms, material names and supported morph controls. The installed
H3 `terrain_fx.hlsl_include` and Reach `templated/terrain_new.hlsl_include` use the
same active-channel normalization and dynamic morph equation. Reach D3D11 adds
its native `1e-8` channel guard before division; that difference is reported.
No ordinary shader or grey fallback stands in for terrain.

Compiled part types are independently composed with shader options: type 3 is
opaque without shadows, type 4 is transparent, and type 5 is lightmap-only.
Alpha cutout, alpha blend and additive behavior stay distinct. Ignored-by-lightmapper
flags remain explicit. See the pinned TagTool schema and the
[C20 H3 authoring conventions](https://c20.reclaimers.net/h3/source-data/h3-materials/)
linked in the catalog.

All 29 materialless instance records have solid flags and **zero source
render-triangle correspondence**. Their exact rings, original edge/vertex indices,
neighboring surfaces, collision-material table, owning definitions and instance
frames are retained. The target is an untextured collision-only shell, with the
target default collision response; no source shader identity or sky meaning is
invented. This reconstruction is labeled medium-confidence inference and reports
the response-material fidelity boundary. It is not a general `material == -1`
rule. The known proof_box structure-sky case remains separately tested.

Collision bits are data driven: two-sided, invisible/sphere-collision-only and
climbable/ladder are preserved. The invisible-to-ray mapping is labeled as an
inference supported by the schema, ASS collision conventions and source grate
geometry, rather than as a quoted H3 engine implementation. Unknown bits and
breakable linkage remain blocking.

The two active unusual images are single-image, depth-one 64x64 cubemaps:
`human_optics` (BC1) and `default_dynamic_cube_map` (BC3), each with seven mip
levels. The adapter emits all six decoded base faces as a TIFF cross, preserving
the complete source mip chains separately in DDS. An independent Pillow BCN
decoder compared every face: maximum channel difference was 1/255. Target cube
orientation and mip generation must still be checked during native import.

The missing loose tree-bark recipe retains its accepted
`STALE_LOOSE_REFERENCE_VERIFIED_RUNTIME_BINDING` classification. The original
reference, retail cache binding/hash evidence and loose H3 `default_vector`
pixels remain separate provenance. No new retail-cache search was performed.

The supplied `ReachTreeBarkXML.zip` now supplies target-side evidence for the
native `bump_detail_map` slot. Its `mp_treebark.shader.xml` binds `base_map` to
`treebark_cedar`, `bump_map` and `bump_detail_map` to `treebark_cedar_bump`, and
leaves `detail_map` empty. The XML gives display names; the full Reach tag
identities come from the supplied HREK inventory. Archive/member hashes and this
evidence boundary are recorded as `REACH_BUMP_DETAIL` in the catalog.

The H3 authoring decision remains
`levels/solo/030_outskirts/shaders/outtree_bark.shader` / `bump_detail_map` →
`shaders/default_bitmaps/bitmaps/default_vector.bitmap`, with source UV transform
`[18, 18, 0, 0]`. The dependency plan explicitly targets the native Reach
`bump_mapping=detail` / `bump_detail_map` binding and Detail Normal Map import
usage. It retains the original parameter, decoded H3 pixels and retail binding
provenance. An empty albedo detail slot does not require a distinct bump-detail
asset. Source `alpha_test=none` and `blend_mode=opaque` remain unchanged; bark
evidence does not establish foliage cutout behavior.

The reported historical `treebark_ceder` names and installed Reach `treebark_cedar`
names are distinct from the absent H3 identity. The community report is retained
as user-supplied context, not independently verified source recovery evidence.
Neither is a replacement candidate. Bitmap archaeology remains closed unless
new exact-identity evidence appears.

Static lighting retains BSP ownership: BSP000 has three definitions and 201
instances; BSP010 has three definitions and 14 instances. The plan also retains
200 sky-light samples and 14 emissive material rows. Scenario light volumes are
separate dynamic `.light` placements, as described in the
[H3 authoring documentation](https://learn.microsoft.com/en-us/halo-master-chief-collection/h3/individual/dynamiclights).
Their source lightmap scale is zero. The plan preserves palette identities,
ordered placement fields and function provenance for runtime work; it does not
invent BSP membership or duplicate them into static lighting-info instances.
An unbound palette index remains explicitly unbound. The missing imported
lighting index at BSP010 material slot 65 is reconstructed from its source shader
identity and embedded resolution/transparency properties, never by reading row -1.

Both structure designs remain intact: `040_voi_000_design` has one boundary mesh
with 33 triangles; `040_voi_010_design` has two with 54 triangles. New unsupported
design fields still enter the same gate.

## Remaining blocking facts

1. **BSP breakable glass surfaces:** BSP010 embedded definition 76, 538 source
   collision surfaces, instances 306–311. The flag does not establish whole-instance
   damage states or destructible scenario scenery. It requires verified shard/support and render-to-collision
   linkage. Foundry explicitly strips the breakable mode from a separate collision
   proxy because Tool otherwise crashes. Preserving the ring while stripping
   breakability would change traversal. Source support/correspondence data are
   retained, but a valid authored breakable reconstruction is not yet established.
2. **Directional emission:** BSP010 lighting material row 97 has power 0.8,
   frustum blend 0.5, falloff 25 degrees and cutoff 45 degrees. Reach material-info
   has focus/attenuation rather than those three frustum fields. The missing facts
   are the H3 angular blend/distribution and area-power normalization needed for a
   source-derived focus or analytical-emitter approximation. No angle was copied
   into an unrelated field, and no emergency light was added.
3. **Inactive-neighbor seam:** global seam table entry 1 joins selected BSP010
   cluster 0 to inactive BSP020 cluster 2. Both source cluster centers agree near
   `(29.5, -90.5, -0.450001)`. The shared 128-bit ID also occurs on other seam-table
   entries, so identity alone is insufficient. `intro_faa` uses mask 3;
   `faa_lakea` uses mask 6. The neighbor was inspected as source evidence only.
   A target construct preserving the inactive-boundary collision/visibility without
   adding BSP020 or inventing closure remains unverified. Foundry's seam import
   expects two BSP owners and skips unpaired source seams; that behavior is not
   accepted as a conversion rule.

### Breakable placement audit

The source-only runner emits `breakable-collision-report.json` and `.md`, with
one row per original contract/placement. It preserves each source BSP and hash,
zone membership, embedded definition identity, placement transform, authored
object name, collision material and render material/shader, flags, surface IDs,
breakable indices and support metadata. Stable original contract IDs link each
row to the full rings, adjacency and render-correspondence evidence. Missing,
duplicate or misowned placements fail the report's accounting check.

The current six rows all belong to
`levels/solo/040_voi/040_bsp_010.scenario_structure_bsp`, embedded definition 76,
render mesh 76. Collision material **38** and render material **78**, part 0,
both identify
`levels/solo/040_voi/shaders/glass/glass_office_spacer_a.shader`.

| Placement | Authored BSP instance name | Breakable collision surfaces |
|---:|---|---:|
| 306 | `?glass_office_spacer_a_12` | 538 |
| 307 | `?glass_office_spacer_a_13` | 538 |
| 308 | `?glass_office_spacer_a_14` | 538 |
| 309 | `?glass_office_spacer_a_15` | 538 |
| 310 | `?glass_office_spacer_a_16` | 538 |
| 311 | `?glass_office_spacer_a_17` | 538 |

That is **538 unique definition surfaces and 3,228 placed surfaces**, still one
original blocking contract. The source flags are 9 (two-sided + breakable).
No external scenery tag or nearby scenario-object association is inferred.

[C20's H3 material convention](https://c20.reclaimers.net/h3/source-data/h3-materials/)
uses `-` for two-sided breakable geometry. The
[H3 scripting reference](https://c20.reclaimers.net/h3/engine/scripting/) describes
`breakable_surfaces_enable(boolean)` as a level-wide breakability control and
`breakable_surfaces_reset()` as restoring the surfaces. The pinned
[TagTool BSP-to-object converter](https://github.com/TheGuardians/TagTool/blob/ce2dc6ac13072b160752af618ea1dc143e2727ac/TagTool/Geometry/Utils/GeometryToObjectConverter.cs#L474)
removes the flag when BSP linkage is lost to avoid crashes. Together these support
the **BSP_BREAKABLE_SURFACES** classification. They do not establish Reach shard
reconstruction. Matching shader identities resolve the material association,
while the per-surface shard/support contract remains blocking. No HSC is generated.

## Reproduce the source gate

Run from the repository in PowerShell. Keep `-PlanOnly`:

```powershell
& .\tools\Run-VoiFactoryAEnvironment.ps1 -PlanOnly `
  -WorkDir 'D:\HaloRE\PortCensus\voi_semantics_20260907\build' `
  -SourceCacheEvidence 'D:\HaloRE\PortCensus\voi_factory_a_environment_1949\runs\20260907-043205-50f73543\h3-stock-cache-bindings.log' `
  -SemanticBaseline 'D:\HaloRE\PortCensus\voi_semantics_20260907\original-unsupported-semantics.json'
```

The recorded rerun is `20260907-113638-4aa8f64e`. It exits 1 with
`BLOCKED_SOURCE_SEMANTICS`, correctly retaining the three unresolved contracts.
Outputs include `environment.plan.json`, `source-semantic-resolution.json`,
`unsupported-semantics.json`, `source-dependencies.json`,
`semantic-mapping-catalog.json`, `original-source-contracts.json`, and
`source-semantic-resolution.md` under that run directory. Supplemental source-only
seam/glass/emissive evidence and independent pixel checks are in
`D:\HaloRE\PortCensus\voi_semantics_20260907`.

The run took 98.4 seconds; semantic planning took 22.9 seconds. Recorded source
stages: H3 scenario/BSP decode 20.7 seconds, material helper excluding bitmap work
0.37 seconds, bitmap decoding 0.72 seconds, sky 2.82 seconds, designs 4.58 seconds,
lighting source exports 8.72 seconds. These are different stage scopes, not an
exhaustive additive wall-time breakdown. Native BSP/instance construction,
GR2/sidecar, Reach Tool, Faux and native validation all remain `NOT_RUN`.

## Validation and publication state

- 69 environment tests passed, including all 46 preserved checkpoint regressions
  and 23 new source-rule/accounting tests.
- 98 scenario tests and 171 import tests passed in separate processes.
- 102 Rust tests passed; one pre-existing test remains ignored.
- Blender 5.2.1 environment construction/lightmap-command smoke test passed with
  synthetic temporary roots and mocked native dispatch.
- All 50 owned proof_box output hashes still match the proven manifest.
- The real rerun balanced all original identities, retained both selected BSPs,
  both designs and the source lighting counts, and wrote zero Voi Reach files.

The existing CI workflow discovers the new tests via `test_h3_environment*.py`.
Remote baseline workflows 34102733635 and 34102733758 were completed successfully
at `4d35ae05821575f612a99d7e659cfe43d05551bd`. These results do **not** validate the
new local checkpoint; remote CI has not run for these unpushed commits. Local
test evidence is recorded separately. This checkpoint does not publish a release
or change normal Foundry feeds.

Proof_box retains Nate's runtime acceptance. Voi Reach data/tags, Tool import,
Faux, scenario generation and Tag Test were not performed.

## Bark/breakable follow-up validation

The follow-up source gate ran as `20260907-120122-7780cebf` using the same
plan-only command above. It completed in 101.1 seconds and correctly returned
`BLOCKED_SOURCE_SEMANTICS`. All original 262 identities, the 14-rule count,
resolution-class totals and the same three blocking identities are unchanged.
It adds the six-placement breakable report and an explicit native bump-detail
binding plan; it does not claim a new breakable conversion rule.

The follow-up environment suite passes **75 tests**, including six additional
report/binding regressions. Existing CI discovers these tests automatically.
The Blender 5.2.1 proof environment construction/lightmap-command smoke test also
passes with synthetic temporary roots; it does not compile Voi or invoke Faux.
The checkpoint remains local and unpushed, so remote CI has not run for it.
The previous Rust/scenario/import results above belong to the preceding semantic
checkpoint; no Rust or native writer implementation changed in this follow-up.

The verification receipt is
`D:\HaloRE\PortCensus\voi_semantics_20260907\breakable-followup-verification.json`.
It records report hashes, unchanged retail binding evidence and decoded bitmap
metadata, exact original-record accounting, all 50 preserved proof_box hashes,
and zero Voi Reach files. Native BSP/instance construction, GR2/sidecar, Reach
Tool, Faux and native validation remain `NOT_RUN`. No further cache search or
normal release/feed publication was performed.
