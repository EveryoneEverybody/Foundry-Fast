# Voi Factory A environment development checkpoint

This checkpoint extends `port_environment` source selection, semantic extraction,
and planning. **It does not produce a playable Voi environment.** The local run
fails closed on unsupported source contracts before any Reach data/tag writes.
The campaign plan uses schema 2; the native authoring worker explicitly refuses
that schema until its multi-BSP writer and validation are implemented. Do not
interpret a complete source decode or a pure planning test as a native compile.

The fetched branch and initial clean HEAD were
`feature/h3-scenario-inspection`,
`4d35ae05821575f612a99d7e659cfe43d05551bd`. Nate's runtime acceptance of the 1.9.48
`proof_box` remains the proven baseline. Its output is not rebuilt or overwritten
by the Voi runner. Existing proof tests remain mandatory.

## Run

```powershell
& 'D:\HaloRE\GitHub\Foundry-Fast\tools\Run-VoiFactoryAEnvironment.ps1'
```

The runner defaults to Nate's H3EK, HREK, Blender 5.2.1, supplied XML archives and
HREK templates. A checkout can use its freshly built source helpers; a standalone
bundle uses `io_scene_foundry/h3_import/bin`. `-Helpers` overrides the helper
directory. `-PlanOnly` uses the same source gate and still returns nonzero for
unsupported semantics. The supported lighting selection defaults to `direct_only`.

The generic CLI accepts `--scenario`, `--zone-set`, `--spawn-flag`, and
`--namespace`. Source and target indices are separate. The named zone must resolve
uniquely; empty/out-of-range masks are rejected. The old no-zone `proof_box`
fixture remains an explicitly tested compatibility case.

The runner can also build the read-only stock H3 cache evidence reader when the
verified Reclaimer checkout is installed at `-ReclaimerRoot`. It checks the
reader revision and a clean source tree before building. `-SourceCacheReader`
accepts an existing reader executable, and `-SourceCache` selects the stock H3
map (defaults to the installed MCC `040_voi.map`). This reader only exports
shader binding metadata. It is not another environment compiler or a tag/pixel
copier. `-SourceCacheEvidence` accepts a previously exported JSON report; the
compiler verifies the actual cache SHA-256 and scenario identity again.
Binding evidence must explicitly declare `source_kind: retail_cache`; regenerate
older reader reports that omit it. The loose source inventory and decoded bitmap
provenance remain `loose_h3ek` even when a retail binding informs the authoring
decision.

Output is reserved under `levels/h3_port/040_voi/factory_a_env` in both Reach
`data` and `tags`. Hash ownership is checked before each attempt. Campaign
selection cannot target `proof_box` or its children. No Tag Test snippet is
created until native generation succeeds.

## Direct source evidence

Live H3 Tool XML and the pinned source decoder establish:

| Relationship | Source value |
| --- | --- |
| Scenario | `levels/solo/040_voi/040_voi.scenario` |
| Zone set | `intro_faa`, index 1, BSP mask 3 |
| Selected BSPs | indices 0 and 1: `040_bsp_000`, `040_bsp_010` |
| Designs | `040_voi_000_design`, `040_voi_010_design` |
| Sky | palette 0: `levels/solo/040_voi/sky/sky.scenery` |
| Spawn flag | `teleport_factorya_player0`, cutscene flag 19 |
| Spawn transform | position `(-10.2022, -108, -1.49976)`, yaw `99.3396` degrees |
| Source BSP placements | 1,183 and 680, including 10 and 6 collision-only placements |
| Cluster portals | 14 and 18 |
| Design triangles | 33 and 54 |
| Sky-light samples | 200 |
| Static light definitions / instances | 3 / 201 and 3 / 14 |
| Nonzero emissive material rows | 7 and 7 |

The inspection ASS output omits the sixteen collision-only placements because
their render meshes have no parts. Opt-in environment extraction now retains
their collision rings, triangles, flags, materials, source definitions and
authored placements. Normal inspection geometry is unchanged. The planner also
retains local instance matrices, part flags, imported-material lighting indices,
portal polygons and cluster relationships.

Voi repeats one 128-bit seam identifier across several seams. Joining on that
identifier alone invents adjacency. Planning checks the parallel source seam
table index, identifier and nonempty cluster mapping together. It validates the
original vertex correspondence before using triangle connectivity. An active
slice edge with no selected partner is reported; it is not assigned a fabricated
neighbor or silently sealed.

## Current source gates and unfinished authoring

The machine-readable report contains exact fields, values, affected surfaces,
instances, definitions and source paths. Current categories include climbable,
breakable and invisible instance-collision flags; unassigned instance collision
materials; non-opaque render-part categories; an unmatched active seam boundary;
material functions/externs pending static-versus-runtime classification;
unsupported shader/image forms; source light-volume
membership/functions; and an active emissive frustum.
The live runner currently reports 262 individual unsupported contracts across
these categories. Both terrain (`sams_club_a_01.shader_terrain`) and foliage
(`outtree_leaf.shader_foliage`) are present. This count is not a count of triangles.

## Missing dependency classification

The previous missing-bitmap blocker was incorrect. A complete installed H3 tags
inventory contains 57,422 files and no exact
`levels/solo/010_jungle/bitmaps/tree_barkc_detail_bump.bitmap`, including no exact
basename elsewhere. Similar `foliage/tree_bark*` names are not used as substitutes.

Its referencing shader, `levels/solo/030_outskirts/shaders/outtree_bark.shader`,
is active on selected BSP 000 material slots 119/120: 18 tree placements and
19,821 placed shader triangles. The selected bump option is `detail`, with
`bump_detail_map` UV transform `(18,18,0,0)` and coefficient 1. This is not an
out-of-zone shader. However, the loose bitmap reference differs from stock H3's
compiled binding.

The installed [Baboon source](https://github.com/Zoephie/Baboon) at
`f4df490579f83697aa7d56ade53abf8071ff5449` supports loose tags and monolithic
`blob_index.dat` inputs, but has no retail `.map` reader. That limits this
recovery route; it does not prove the missing reference is required or
unrecoverable. A read-only diagnostic using the official
[Reclaimer library](https://github.com/Gravemind2401/Reclaimer) at
`6209415badf398a17a895d4d726b67eea850c67f` inspected the installed stock caches.
Both `040_voi.map` and `030_outskirts.map` bind this exact shader's
`bump_detail_map` to the H3 bitmap
`shaders/default_bitmaps/bitmaps/default_vector`. Both parsed tag indexes lack
the supposedly required `tree_barkc_detail_bump` bitmap. Shader category choices,
sampler names, UVs and constants match the loose shader.

The generic audit therefore classifies this as
`STALE_LOOSE_REFERENCE_VERIFIED_RUNTIME_BINDING`. The Voi build uses only
matching-scenario cache evidence for its authoring decision. The separate
`authoring-shader-manifest.json` references the existing, decoded H3
`default_vector` pixels, reusing the source bitmap cache; the original
`shader_manifest.json` and authored reference remain intact. There are 337
effective bitmap entries instead of 338. No Reach fallback assets or cache
resource payloads are used.

The same audit records 35 absent authored references outside the resolved
selected option parameter sets, including `outtree_bark`'s `height_map` while
parallax is off. Those are not runtime blockers. Missing active references
without sufficient evidence remain unresolved and report the exact source,
parameter, surfaces, placements and cache recovery requirement. A mismatched
cache hash, mission, option, sampler, transform or constant cannot authorize an
override. Incomplete shader decoding cannot establish that a reference is unused.

Each run saves the complete name inventory, dependency report, cache reader
invocation, cache hash, reader revision, source shader/bitmap hashes and usage
relationships. The latest live audit took 8.74 seconds; the full source/planning run
took 93.22 seconds and created no Reach output. These timings are local evidence,
not performance guarantees.

### Assembly retail-cache recovery check

A subsequent read-only scan used current
[XboxChaos Assembly source](https://github.com/XboxChaos/Assembly/tree/fd14ef3c46135e9422966c6a64cd926fb0bd23fb)
(`dev`, `fd14ef3c46135e9422966c6a64cd926fb0bd23fb`). A headless .NET Framework 4.8
diagnostic compiled unmodified Blamite source and used Assembly's tag/name-table
APIs. Steam registry, library metadata and the MCC app manifest located the maps;
the root was not assumed.

All 48 installed `.map` files parsed successfully. Forty identify as Halo 3 MCC
Update 14; the eight Reach Toolset caches in the same folder were classified
separately. Across the H3 caches, all 453,720 valid tags and 453,732 filename-table
entries contain **zero exact identity or exact bitmap-basename matches** for
`levels/solo/010_jungle/bitmaps/tree_barkc_detail_bump.bitmap`.

| Required cache | Valid tags | Filename entries | Exact bitmap matches |
| --- | ---: | ---: | ---: |
| `010_jungle.map` | 14,591 | 14,592 | 0 |
| `040_voi.map` | 17,453 | 17,454 | 0 |
| `campaign.map` | 0 | 0 | 0 |
| `shared.map` | 0 | 0 | 0 |

A separate full-file ASCII scan also found no exact full path. Its three
basename-substring hits are the different
`levels/multi/deadlock/bitmaps/deadlock_tree_barkc_detail_bump` identity in
`bunkerworld.map`, `deadlock.map` and `isolation.map`. Parsed tag entries confirm
that distinction; none was substituted.

Shared/campaign headers have no tag or filename tables but do contain raw
resource pools. No metadata/resource-datum/page chain connects their anonymous
bytes to this bitmap. **No metadata, raw bitmap resource, pixels, `.tagc`, or
loose EK `.bitmap` for the requested identity was recovered.** Absence of a named
tag is not proof that equivalent anonymous pixels are absent from a raw pool.

Assembly's verified normal tag export uses a `.tagc` container with metadata and
resource pages, including extracted page bytes when resource extraction succeeds.
It does not itself establish a reconstructed loose EK bitmap. The exact requested
tag was absent, so that extraction path was not exercised for it. This result
describes this installed cache set, not every historical H3 cache release.

The local evidence lives in
`D:\HaloRE\PortCensus\retail_treebark_20260907\retail-recovery-report.json` and its
Markdown companion, with per-cache tag/name dumps, source revision, hashes,
shared headers, source-contract links and the different-name classification.
All 48 cache hashes agree between the two full-file reads and all 96 dump hashes
verify. Provenance is `retail_cache`. This negative inventory does not authorize
a binding change; the earlier positive Voi sampler evidence remains separate.

## Remaining authoring work

All four candidate scenario `.light` palette tags are exported and hashed.
Their ordered field records preserve repeated field names and keep opaque
function payloads as source evidence. The palette contains sphere/frustum lights,
including gel-bitmap references. Membership and function interpretation remain
unresolved, so these records cannot become invented static lights.

The active frustum is material-info row 97 in BSP 010 lighting info: emissive
power 0.8, frustum blend 0.5, angles 25/45 degrees. The paired Reach material-info
schema has no corresponding frustum fields. These values are retained and
rejected, not treated as zero emission.

Design and static-light conversion currently produce **plans**. They have not
been written into native Reach design or lighting-info tags. Terrain recipes
remain in the canonical shader-helper snapshot; the existing terrain blending
implementation is an inspection preview, while `ReachStager` currently accepts
`rmsh`. This checkpoint does not mislabel that preview as native terrain support.
The native multi-BSP construction, instance proxies, design export, seam/portal
export, native material/terrain adapters, lighting readback gate, Tool/Faux run,
and Tag Test packaging remain unfinished.

## Evidence and validation

The authoring oracles are inspected and hashed without executing their scripts
or copying their geometry. Local `gr2-to-json` inspection of the two supplied
GR2 templates confirmed Reach connected-geometry metadata and the sky sample
properties. The sky `.blend` and `.fbx` are supporting source formats, not port
assets. Read-only Blender inspection with automatic script execution disabled
found 209 numbered skylight objects in the `.blend`; Blender's binary FBX parser
also found 209 light node attributes in the FBX 7400 file. The supplied generation
script is read only.

[C20's H3 material authoring documentation](https://c20.reclaimers.net/h3/source-data/h3-materials/)
describes sky indices, portals, seams, seam sealers, collision/render-only faces,
soft boundaries and lightmapper flags. These are authoring categories, not proof
that an arbitrary compiled source field has an equivalent Reach representation.
Foundry's existing portal, seam, boundary and lighting writers provide the target
contracts; their existence alone does not establish conversion parity.

Pure CI tests cover mask selection, multiple BSP plans, strict namespace scope,
source starts, soft-boundary planning, static-light units, collision-only instance
coverage, portal flags, repeated seam identifiers, and canonical shader dedupe.
The original 20 proof-box tests and Blender construction/Faux dispatch smoke
remain in place. CI never claims to run HREK or Tag Test.

Local verification passed 46 environment tests, including rejection of absent or
incorrect cache provenance. The live reader rebuilt with zero warnings/errors;
run `20260907-043205-50f73543` verified distinct `retail_cache` binding evidence and
`loose_h3ek` pixel provenance, with no dependency-audit failures. It still stopped
at 262 unsupported source contracts before Reach writes.
The earlier broader verification passed 98 scenario tests and 171 import tests.
The source-helper suite passed 101 tests with one pre-existing ignored
test. The updated scenario helper separately passed its 74 tests after the final
metadata changes. Blender 5.2.1 passed the original environment smoke test.
All 50 existing proof-box output files match their ownership hashes.

A shared pre-Faux readback gate checks each native sky and BSP lighting-info tag
individually. It rejects missing light definitions/instances, a zero-emission
result for meaningful source emission, and sky samples without positive energy.
Read-only validation against the existing proof tags passed: 200 sky samples,
zero generic definitions/instances and zero emissive rows. It did not rebuild the
proof or run Faux. This count/energy gate is not photometric or material-surface
parity validation, which remains necessary for campaign authoring.

Build reports retain the source hashes, helper/tool invocations, timings, selected
relationships, source geometry references and unsupported records. A blocked run
reports zero Reach lights written and `NOT_RUN_SOURCE_GATE`; it must not run Faux.
Native stages have `NOT_RUN`, not a fabricated zero-duration success.

After a future accepted native build, Nate's runtime command will be:

```text
game_start levels\h3_port\040_voi\factory_a_env\factory_a_env
```

Runtime acceptance is pending Nate. This checkpoint does not start scenario
objects, machines, AI, HSC, characters, animations, audio, effects or cinematics.
