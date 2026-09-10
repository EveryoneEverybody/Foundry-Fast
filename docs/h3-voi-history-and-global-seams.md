# Voi historical bark provenance and global seam ownership

This follow-up validates all 262 original source records with zero blockers and
14 rules using the preserved source snapshot, retaining the tested checkpoint
`5565b095034cbaacf26e0dae8e5ebc3a2361287a` on
`feature/h3-scenario-inspection`. It updates provenance and the global seam plan;
no native Voi content is generated.
The installed bark shader was edited after that snapshot. Its fresh gate is
separately blocked; Nate explicitly selected original-snapshot verification and
instructed that the installed edits remain untouched.

## Historical source, retail authoring decision

Nate relayed confirmation from modders with access to cut H3/Digsite content:
`tree_barkc_detail_bump.tiff` is a genuine historical H3 authoring asset. Its
texture content matches the supplied `deadlock_tree_barkc_detail_bump.tiff`, whose
name adds the `deadlock_` prefix. The unprefixed original was not supplied locally
for an independent byte/pixel comparison; the report keeps that verification limit.

The supplied TIFF was preserved unchanged outside the repository:

- Dimensions: 256 by 1024; 1,048,830 bytes.
- SHA-256: `3ab5044e3400d10fe53f0471e9863b17c86717340c6b328563ffde694ee65368`.
- Local evidence: `D:\HaloRE\PortCensus\voi_semantics_20260907\global-seam-history-evidence\source-history`.

The source-history classification is **HISTORICAL_H3_AUTHORING_ASSET**. With the
verified retail binding, the dependency row now reports
**HISTORICAL_AUTHORING_REFERENCE_VERIFIED_RUNTIME_BINDING**. It preserves the
previous runtime-resolution classification as a separate field: "stale" describes
the installed loose shader's reference relative to the shipped sampler; it does
not claim the historical texture was invented or never existed.

The authoring decision remains exactly:

```
retail 040_voi.map
  outtree_bark.bump_detail_map
  -> shaders/default_bitmaps/bitmaps/default_vector.bitmap
  -> decoded H3 source pixels, original H3 UV transform, native Reach bump-detail slot
```

The historical TIFF has **no runtime-binding authority**. It is source-history
evidence and optional future authoring-reconstruction evidence. It is not included
in the active shader/bitmap manifest. Original loose recipes, verified retail
cache hashes, default-vector source hashes/pixels and UVs remain intact. No further
bark cache archaeology or name-based substitution was performed.

`--source-history-evidence` / `-SourceHistoryEvidence` accepts an explicit JSON
document keyed by exact source bitmap identity. The compiler verifies artifact
size/hash and preserves the stated origin, confidence and verification limits.
History cannot clear an unresolved runtime dependency, rewrite its original
diagnostic, or substitute a texture. Invalid authority, changed artifacts and
duplicate identities fail explicitly. These are reusable provenance rules.

## Reach stores seam ownership globally

Read-only exports from installed stock Reach **m20** establish the requested
target-side example. Its scenario references one `m20.structure_seams` resource
containing 20 seams. Global seam **13** joins:

- Scenario BSP index **4**, `m20_015`, clusters **0 and 1**.
- Scenario BSP index **5**, `m20_020`, clusters **7 and 2** respectively.

Both BSPs have the same global seam index and 128-bit identifier, 191 valid edge
mappings and matching cluster centers. The global seam has 191 original vertices
and 189 triangles. Ownership is established by these relationships, not by a
repeated identifier alone.

| Stock Reach zone set | BSP mask | Seam 13 owners loaded | Connection active | Global seam retained |
|---|---:|---|---|---|
| zoneset_courtyard_valley | 57 | 4 + 5 | Yes | Yes |
| zoneset_exterior | 225 | 5 | No | Yes |
| zoneset_end_cinematic | 7 | Neither | No | Yes |

The stock tags establish global ownership across the zone masks. The separately
verified Reach runtime predicate establishes activation only when both owners are
connected. This is a streaming relationship with valid source geometry, not a
missing-boundary source error.

The local `reach-global-seam-ownership.json` evidence report records exact source
tag and export hashes, commands, ownership and all 18 m20 zone states. Only stock
tag XML exports were run. Stock tag hashes were unchanged after inspection.

## Existing Foundry behavior and the bounded Voi build

Foundry's active exporter creates paired seam meshes with
`bungie_mesh_seam_associated_bsp`, reverses the back-facing copy, and requires
both owner regions to exist in its authoring region set. Its scenario sidecar
declares the scenario-level `structure_seams` output. Scenario zone-set BSP flags
are stored separately.

The `BSPSeam` and `StructureSeamsTag` helpers reconstruct paired ownership from
cluster mappings and assign front/back regions. The main scenario importer
currently comments out BSP seam discovery. Helper support is therefore evidence
of representation, not proof of end-to-end automatic seam import.

For Voi, the plan now explicitly retains the scenario-global relationships:

| Global seam | Owners | intro_faa, mask 3 | faa_lakea, mask 6 |
|---|---|---|---|
| 0 | BSP000 + BSP010 | Active | Inactive |
| 1 | BSP010 + BSP020 | Inactive | Active |

The global seam semantic is **NATIVE_DIRECT**. The original selected-slice record
remains **NATIVE_TRANSFORM**, with zero blocking unknowns: its plan retains global
ownership and explains the bounded build projection. Global authoring requires
both owner BSPs to exist in the target scenario; active zone membership determines
which are loaded. Once both target owners exist, retain the native paired seam
globally even in zones where one is inactive.

This task still builds no native assets and selects only BSP000+010. It adds no
BSP020 reference or resources. Seam 1's geometry/ownership remain in the plan.
Its verified source collision surface 5332/material 62 remains preserved for the
bounded slice, within 0.0000293984456 world units of the global seam geometry.
No closure is invented. The earlier caution against an unmapped Reach `IsSeam`
material applies only to incomplete target authoring; it does not describe a
properly mapped global seam with an inactive owner.

## Verification results and the changed installed source

The fresh run `20260907-135503-59b6f518` correctly returned
**BLOCKED_SOURCE_SEMANTICS**. Its installed `outtree_bark.shader` differs from the
clean original:

- Original SHA-256: `ea5baa6f458a93ca6fdeeee9e3b8c7b407e569ee232596f86d0ef6fbbb343364`.
- Observed installed SHA-256: `20a32a6c51fbc94544e8d1dbb084fedf0e49c64579923c4e993f1cf1ecfefd97`.
- Parallax changed from `off` to `simple`; `bump_detail_map` now names the Deadlock
  bitmap, and `height_map` activates missing `tree_barka_height.bitmap`.

That observed recipe did not match the verified retail shader configuration.
The gate preserves the missing original function-contract ID and reports the new
active dependency, instead of using historical evidence to approve either change.
This is recorded input drift, not a reopened seam unknown. No attempt was made to
restore or modify the installed tag.

As Nate requested, the original decoded source/authoring snapshot was replayed
through the compiler's current pure semantic resolver. Input hashes and the prior
clean-plan verification receipt are retained. This is **not** a fresh source decode.

| Validation basis | Original records | New records | Blocking | Rules |
|---|---:|---:|---:|---:|
| Preserved original snapshot replay | 262 | 0 | 0 | 14 |

All 262 original record IDs/classes/rules, the retail binding, source UVs, bitmap
plans, source hash table and selected BSP mask remain unchanged. Accounting is
81 NATIVE_DIRECT + 83 NATIVE_TRANSFORM + 86 NATIVE_REBUILD + 10 STATICIZED_MVP +
1 OPTIONAL_MVP_OMISSION + 1 RUNTIME_LATER = **262**.

The updated plan, resolution, mapping catalog, dependency/history audit, seam
context and snapshot receipt are in
`D:\HaloRE\PortCensus\voi_semantics_20260907\global-seam-history-evidence\original-source-replay`.
The separate fresh-run result is retained in its original run directory.

Validation passed: **95 environment**, **98 scenario**, **171 import** tests and
the Blender **5.2.1** proof geometry/lightmap-command smoke. The smoke uses
temporary synthetic roots and intercepts native dispatch. Existing CI discovers
the new tests automatically; remote CI has not run for this local checkpoint.

## Reproduce the source gate and snapshot verification

From `D:\HaloRE\GitHub\Foundry-Fast`:

```powershell
& .\tools\Run-VoiFactoryAEnvironment.ps1 -PlanOnly `
  -WorkDir 'D:\HaloRE\PortCensus\voi_semantics_20260907\build' `
  -SourceCacheEvidence 'D:\HaloRE\PortCensus\voi_factory_a_environment_1949\runs\20260907-043205-50f73543\h3-stock-cache-bindings.log' `
  -SemanticBaseline 'D:\HaloRE\PortCensus\voi_semantics_20260907\original-unsupported-semantics.json' `
  -SourceHistoryEvidence 'D:\HaloRE\PortCensus\voi_semantics_20260907\global-seam-history-evidence\source-history\history.json'
```

The source-history TIFF and stock XML exports are local evidence, not bundled
game assets. The mapping catalog records provenance and semantic facts only.
The historical texture is never staged into Reach by this command.
The command above reads the installed source. The recorded fresh run failed on
the changed recipe described above; subsequent installed edits are outside this
snapshot validation. A new installed-source result requires its own fresh run.

Replay the original snapshot without touching those installed edits:

```powershell
python 'D:\HaloRE\PortCensus\voi_semantics_20260907\global-seam-history-evidence\verify-original-snapshot.py'
```

This local verification harness calls the same pure `port_environment` planning
and semantic rules. It does not invoke extraction or a native writer. The original
262 diagnostics and source recipes stay immutable; target rule output is
recomputed on an in-memory copy and labeled `ORIGINAL_SOURCE_SNAPSHOT_REPLAY_PLANNED`.

All 50 proof_box output hashes and the four inspected stock Reach tag hashes
remain unchanged. There are no files in the Voi Reach data/tag namespace. No Voi
Tool import, Faux, Tag Test, normal release or feed publication occurred.
