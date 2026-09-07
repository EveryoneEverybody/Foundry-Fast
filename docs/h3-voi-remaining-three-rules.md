# Voi source gate: remaining three rules closed

The installed-source rerun `20260907-132606-ea4a6c77` completed with **PLANNED**,
exit 0: **262 original records, 262 resolved, zero new or blocking records**.
The compiler still uses **14 unique semantic rules**. This checkpoint changes
only the three remaining source rules, their evidence, tests and reporting.
It does not build native Voi assets or claim runtime acceptance.
The [historical bark and global seam follow-up](h3-voi-history-and-global-seams.md)
clarifies scenario-global ownership versus active zone membership and updates
source-history provenance while preserving the retail authoring decision.

Branch: `feature/h3-scenario-inspection`. The published, runtime-proven proof_box
baseline remains `4d35ae05821575f612a99d7e659cfe43d05551bd` (1.9.48).
The stopped local source-planning work was preserved unchanged in
`022dff1d296d25fd7e2b1865c9115f6de71bc102`; the 259-record resolution is
`fdb4476b9b3d424d98b1c3b6ca678dc7c6c5c154`, and the bark/breakable report follow-up is
`ceb61563b3a5305003c28824430a13738d13d59d`. This pass started clean at that last
commit, recorded status before fetching metadata, and preserved all three commits.
No reset, clean, destructive checkout, rebase or stash operation was used.

## The three decisions

| Source contract | Previous blockers | Current blockers | Resolution |
|---|---:|---:|---|
| BSP010 definition 76 breakable glass | 1 | 0 | NATIVE_REBUILD |
| BSP010 lighting material row 97 frustum | 1 | 0 | NATIVE_TRANSFORM, explicit approximation |
| Global seam 1, inactive BSP020 neighbor | 1 | 0 | NATIVE_TRANSFORM, selected source state |

### Unified breakable glass

Collision slot **38** and render slot **78**, part 0, resolve to
`levels/solo/040_voi/shaders/glass/glass_office_spacer_a.shader`. Embedded definition
and render mesh **76** bind to decoded render object **103** through the existing
name/full-transform-verified instance planner; the offset is not hard-coded.
Placements **306–311**, authored names `?glass_office_spacer_a_12` through `_17`,
all retain their original transforms and per-vertex lighting policy.

The pure geometric proof finds:

- 538 source collision rings: 496 triangles and 42 quads, all flags 9
  (two-sided + breakable).
- 580 render triangles and complete coverage of every collision ring and render
  face. Opposite geometric copies agree exactly in UV, color and weights and
  have opposite normals.
- **269 unique collision polygons / 290 unified render triangles**, shared by
  all six placements. There are 3,228 placed source collision surfaces.
- Maximum local vertex error **0.0000085299224 ASS units**; maximum source-plane
  error **0.0000090263436 ASS units**. The recorded matching tolerance is
  0.0001220703125 ASS units, eight float32 ULPs at this local magnitude. Distinct
  render positions are never welded by proximity; ambiguous matches fail.

Each ring includes the exact source edge/vertex IDs, oriented plane reference,
material identity, matching render triangle IDs, boundary-edge coverage and area
error. The original compiled triangle mapping stays as audit evidence; the proof
does not infer its meaning from integer values alone.

The target contract is one native Reach scenario mesh with `FaceMode.breakable`
and two-sided faces, generating **both render and collision**. Opposite duplicate
faces become one two-sided face only after corner-attribute equivalence is proved.
The plan explicitly suppresses the separate collision proxy for this definition.
Foundry's existing writer strips breakability from such proxies to avoid a Tool
crash; that backend is unchanged.

Reach Tool must rebuild its breakable support/surface IDs from the unified source
geometry. H3 compiled shard/support indices remain provenance, not copied payload.
The geometric and material correspondence is established; target compiled
membership and fracture behavior remain native/runtime validation obligations.

Nate's glass screenshot is retained locally with SHA-256
`86c703a776854033e9baa808fef3eaf9310de391198ef57165109d3504cbd380`.
It confirms the office-divider pane intent independently of the numeric proof.
[C20's breakable material convention](https://c20.reclaimers.net/h3/source-data/h3-materials/)
and the BSP breakable-surface controls support this classification; it is not
whole-instance destructible scenery. The six-placement JSON/Markdown inventory
still contains the complete original source identities and counts.

### Directional emissive approximation

Source lighting row **97** binds to BSP010 material slot **94**, shader
`levels/solo/040_voi/shaders/lights/metal_doodad_a_illum_cool.shader`.
It retains power **0.8**, color **(0.635294, 0.756863, 0.827451)**, quality 1,
distance attenuation **falloff 1 / cutoff 2 world units**, and flags 1.

The H3 angular inputs are blend 0.5, falloff 25 degrees, cutoff 45 degrees and
basic focus 0. The exact H3 photometric law has not been recovered. The explicitly
chosen MVP model `solid_angle_equivalent_cone_v1` uses the following assumptions:
angles are half-angles about the authored face normal, the frustum transition is
linear in cosine, and blend weights its angular integral against the basic cone.

```
cos_frustum = (cos(inner_angle) + cos(outer_angle)) / 2
cos_basic = cos(pi * (1 - source_focus) / 2)
cos_effective = (1 - blend) * cos_basic + blend * cos_frustum
Foundry spread = 2 * acos(cos_effective)
Reach focus = 1 - spread / pi
```

This yields Foundry spread **2.311234845254898 radians** and native Reach focus
**0.26431109946290243**. Foundry's export and import code implement the stated
spread/focus roundtrip, and its area-light conversion uses `light.spread` for the
same property. The contradictory property tooltip is documented; no proven writer
was rewritten. No angle is used as distance attenuation.

Fidelity loss is the H3 angular falloff/cutoff/blend shape and unverified exact
photometric normalization. Source power, color, quality, distances and face-normal
emission remain intact. No light placement is invented. Unknown flags, invalid
angles, zero/nonfinite source power, invalid attenuation or an unresolved material
identity still block this rule. The next native build must verify the nonzero
compiled emissive row before Faux.

### Inactive-neighbor seam

Read-only disassembly of the installed **H3 and Reach runtime executables**
establishes the activation predicate: both connected-owner bytes must differ from
`-1`. Connecting/disconnecting BSPs updates those owners and recomputes the active
mask. This is stronger evidence than a debug-overlay color interpretation.

| Runtime | Executable SHA-256 | Active-mask calculator RVA | Collision-material mask initializer RVA |
|---|---|---|---|
| H3 | `59a78f2c96034d7ceb5d710505b2b36813aa141fc81a083e3f952973dbce4602` | `0x4b2230` | `0x4b1f10` |
| Reach | `cbdd8448a87a433b0dffc0de47d06db7a18b4bf868b96b057135daa86790aba8` | `0x12c800` | `0x12b9b0` |

Both image bases are `0x140000000`. Assertion-string cross-references identify
the seam subsystem; raw branch instructions establish the owner tests and bit
updates. Local assembly listings and inspection scripts remain outside the repo.
The mapping catalog contains hashes, exact branch RVAs, claims and evidence limits;
it contains no executable bytes. Neither runtime executable was run or modified.

**H3 retains the existing seam collision material when that mapped seam is
inactive**, and suppresses it when both owners connect. Reach behaves the same for
mapped seams, but skips an **unmapped `IsSeam` material with mapping -1**. Therefore
merely exporting a lone Reach seam can lose required collision.

The selected slice instead retains the exact source collision triangles as native
ordinary `collision_only` faces. It emits no 010-to-020 connector. This is the
already-authored H3 collision face, not newly generated closure geometry or a
seamsealer guess. Its original seam identity and geometry remain in the plan for
future paired-zone authoring.

Global seam **1** joins BSP010 cluster **0** to BSP020 cluster **2**. Source BSP010
collision material **62**, surface **5332**, triangles **9844–9845**, decoded
collision object **173**, cover the original seam boundary exactly within XML
coordinate precision: maximum vertex error **0.0000293984456 world units**.
Global index, identifier, cluster/edge mappings and geometric correspondence
disambiguate the repeated 128-bit identifier.

| Source zone | BSP mask | BSPs | Seam 1 connection | Existing seam collision |
|---|---:|---|---|---|
| intro_faa | 3 | 000 + 010 | Inactive | Extant |
| faa_lakea | 6 | 010 + 020 | Active | Suppressed |

The runner reads BSP020's seam metadata as evidence only. Its source hash is
`dda3b9b0401d1fce51414a7aaf08852fb16493a8fbec96fcb322ba002f97733f`.
The selected build remains BSP000+010; no BSP020 render, collision or material
content is added. The [H3 seam workflow](https://learn.microsoft.com/en-us/halo-master-chief-collection/h3/bsp/bsphome)
and [C20 zone-set example](https://c20.reclaimers.net/h3/guides/map-making/level-creation/blender-level-modeling/blender-level-creation-additional-info/#zone-sets)
provide authored context. Native paired seams remain the next writer's path when
both owners exist in the target scenario, independently of whether both are active
in every zone set; no compiled PVS or adjacency is copied.

## Balanced accounting and preserved scope

| Class | Records |
|---|---:|
| NATIVE_DIRECT | 81 |
| NATIVE_TRANSFORM | 83 |
| NATIVE_REBUILD | 86 |
| STATICIZED_MVP | 10 |
| OPTIONAL_MVP_OMISSION | 1 |
| RUNTIME_LATER | 1 |
| BLOCKING_UNKNOWN | 0 |
| **Total** | **262** |

All 262 IDs match the immutable original fixture; there are no vanished IDs and no
new contracts. The earlier 259 resolutions are unchanged in class/rule. Existing
terrain, foliage, cube-pixel and cosmetic-animation approximations remain recorded.
The accepted retail bark `bump_detail_map -> default_vector` binding and source UVs
are unchanged; there was no further bark cache archaeology or asset substitution.

The plan retains authored `intro_faa` mask 3, both structure designs, the real H3 sky,
Factory A spawn flag 19, 200 sky samples, 215 BSP static light instances and 14
emissive material rows. **No Voi Reach data or tags were written.** No Reach Tool,
Faux, Voi scenario generation or Tag Test ran. Proof_box retains Nate's acceptance.

## Reproduce and inspect

From `D:\HaloRE\GitHub\Foundry-Fast` in PowerShell:

```powershell
& .\tools\Run-VoiFactoryAEnvironment.ps1 -PlanOnly `
  -WorkDir 'D:\HaloRE\PortCensus\voi_semantics_20260907\build' `
  -SourceCacheEvidence 'D:\HaloRE\PortCensus\voi_factory_a_environment_1949\runs\20260907-043205-50f73543\h3-stock-cache-bindings.log' `
  -SemanticBaseline 'D:\HaloRE\PortCensus\voi_semantics_20260907\original-unsupported-semantics.json'
```

The run directory is
`D:\HaloRE\PortCensus\voi_semantics_20260907\build\runs\20260907-132606-ea4a6c77`.
It contains `environment.plan.json`, `source-semantic-resolution.json`, the empty
`unsupported-semantics.json`, `source-dependencies.json`, `semantic-mapping-catalog.json`,
`source-seam-context.json`, `original-source-contracts.json`, the six-placement
breakable inventory and `source-semantic-resolution.md`.

Wall time was **138.2 s**, including **25.3 s** of semantic planning. Source stages:
scenario/BSP decode 23.47 s, materials excluding bitmap work 0.79 s, bitmaps 0.96 s,
sky 3.07 s, designs 2.56 s, lighting exports 9.76 s. Stage scopes are not an additive
wall-time breakdown. Native BSP/instance construction, GR2/sidecar, Reach Tool,
Faux and native validation all report `NOT_RUN`.

Validation: **89 environment tests**, **98 scenario tests**, **171 import tests**,
and the Blender **5.2.1** proof-environment construction/lightmap-command smoke test
pass. That smoke uses synthetic temporary roots and mocked native dispatch.
All **50 proof_box output hashes** remain identical. Rust/helper code was unchanged;
the earlier checkpoint's Rust results are historical, not a new run here.

Existing CI discovers the added tests through `test_h3_environment*.py` and needs
no H3EK/HREK. This checkpoint is local; **remote CI has not run for it**. No normal
Foundry release or feed was published. Work stops at the clean source gate.
