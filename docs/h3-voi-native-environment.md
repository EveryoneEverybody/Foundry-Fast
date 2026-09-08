# Voi Factory A native environment, prototype 1.9.49

The shared `port_environment` compiler can lower the accepted H3 `040_voi / intro_faa` snapshot into native Reach authoring. It builds BSP000 and BSP010, their two structure designs, the H3 sky, materials, collision, BSP instances and authored static lighting. It creates one Reach zone set and the `teleport_factorya_player0` start. Scenario objects, AI, HSC, effects and mission logic remain outside this milestone.

Runtime acceptance is **PENDING NATE**. A successful build means native import, lighting and reference checks passed; only Tag Test can confirm the resulting experience. The separate 1.9.48 `proof_box` output remains the runtime-proven regression fixture.

## Build the accepted original source snapshot

The installed `outtree_bark.shader` was subsequently edited by the user. This invocation verifies and uses the preserved original snapshot without restoring or reading that edited shader:

```powershell
& 'D:\HaloRE\GitHub\Foundry-Fast\tools\Run-VoiFactoryAEnvironment.ps1' `
  -AcceptedPlan 'D:\HaloRE\PortCensus\voi_semantics_20260907\global-seam-history-evidence\original-source-replay\environment.plan.json' `
  -WorkDir 'D:\HaloRE\PortCensus\voi_factory_a_native_20260907\build'
```

The runner defaults to Nate's H3EK, HREK and Blender 5.2.1 installations. `-PlanOnly` remains available. A portable checkout needs its own accepted source snapshot; neither that snapshot nor proprietary source assets belong in CI or the extension package.

Generated authoring and tags are owned under `levels/h3_port/040_voi/factory_a_env`. Shader infrastructure additionally lives under `tags/shaders/h3_port/040_voi/factory_a_env`: Reach requires render-method definitions used for template generation beneath `shaders`, so these unchanged target definitions have a separate, equally guarded namespace. The ownership manifest covers all three roots and rejects unowned or externally modified files. Stock Reach definitions are read as infrastructure evidence and remain untouched.

## Native build and validation

1. Verify the accepted plan, canonical decoded geometry, original/effective shader manifests and preserved source pixels. The original 262 records remain balanced through 14 semantic rules with zero blocking unknowns.
2. Reuse canonical shader/bitmap identities. Stage 159 native shaders, including explicit `.shader_terrain` and `.shader_foliage` groups. Preserve source textures, alpha/cutout semantics, constants and UV transforms. Native readback verifies shader options, parameters, samplers and bitmap references.
3. Export source pixels with the Standard texture transform, avoiding AgX display tonemapping. The two required cubemaps retain all six faces and use Reach's native cross layout; readback uses Reach's own bitmap decoder. Reuse only TIFF/bitmap pairs with matching snapshot and ownership hashes, including receipts from an earlier successful bitmap stage when a later stage failed.
4. Construct shared local definitions and all 1,863 BSP placements, including 16 collision-only placements. Reconstruct collision polygons from source rings. The six office-glass placements use unified, two-sided `FaceMode.breakable` geometry, with no separate breakable collision proxy.
5. Export normal Foundry GR2/sidecar authoring. Force Reach's instance import to rebuild: an incremental import was empirically found to retain BSP material indices while omitting their instance-emissive rows from the new lighting table. A forced import regenerates consistent tables. Bitmap caching remains enabled.
6. Write the six source static-light definitions and 215 instances using Foundry's typed Reach lighting writer. Before Faux, verify every definition/placement and all 14 source-positive emissive material records by shader identity and complete power/color/focus/attenuation values. Tool may deduplicate identical lighting rows: both BSPs have six positive native rows. Verify 200 source sky samples and the source sun.
7. Run `direct_only` Faux. Require successful process exits, successful logs and finite nonzero lighting energy. There are no emergency lights or stock-world substitutions.
8. Read native scenario membership, spawn transform, every instance transform/collision presence, breakable render/collision links, design geometry/winding, active seam ownership and inactive-boundary collision. Audit full native tag reference identities with ManagedBlam, then open all generated native tag groups with Reach Tool. Stream large XML exports; real lightmap data exceeds the small-fixture parser's 32 MiB limit. The fixture limit and entity rejection remain intact.

The active seam is 000↔010. Source seam 010↔020 remains in global provenance for future zone sets. This bounded target contains no BSP020 reference. Its extant H3 collision surface 5332 is retained as ordinary collision and checked geometrically in the generated BSP, without adding a closure or connection.

The two design tags preserve `voisky` (33 and 22 triangles) and `camera_fa_01` (32 triangles). Validation compares oriented geometry within 0.0001 world units. Tool regenerates bounds, clusters and portal topology from all authored source polygons; compiled cluster/portal counts need not equal H3's compiled tables.

## Explicit fidelity limits

- The accepted staticization rules freeze cosmetic material functions at their source/default state. Required alpha cutout, collision and visibility semantics remain active.
- H3 single-lobe/glass BRDF options use Reach's supported two-lobe material model while preserving texture/alpha bindings. Unexposed anti-shadow/area-specular controls and bounded glass Fresnel controls have explicit parameter-level decisions. Unknown or unsafe parameters still fail.
- H3 anisotropy levels 1 and 3 use Reach's next supported levels 2 and 4. Addressing and UV transforms remain unchanged.
- H3 directional emissive frustum semantics use the accepted source-derived focus approximation. The active power 0.8 remains nonzero, with focus about 0.264311 and source attenuation distances 1/2 world units. Exact photometric parity is not claimed.
- H3 shared per-pixel lightmapping uses Reach per-pixel authoring. Imposters are disabled explicitly, retaining full geometry. Lightmap density requests use Reach's supported density range.
- The render-only sliver filter records 21 removed triangles across unique source meshes/definitions in this slice. It never processes collision or unified breakable geometry. Thresholds and every source face ID are retained in the worker report.
- Reach Tool performs its ordinary topology optimization. Source polygon authoring and source IDs remain in the blend/plan; native counts, duplicate-triangle warnings and invocations remain in the report.

The bark source-history correction is preserved: `tree_barkc_detail_bump` is a genuine historical H3 authoring asset. The active retail Voi binding remains H3 `default_vector`, with its source UV transform. Historical/Reach cedar textures are not used as replacements.

## Tag Test

Use the snippet only after the build report says `GENERATED`:

```text
game_start levels\h3_port\040_voi\factory_a_env\factory_a_env
```

Confirm loading, Factory A spawn, H3 geometry/materials/terrain/sky, plausible lighting, walking collision and the active BSP boundary. Runtime acceptance is recorded separately from Tool/Faux/CI results. No normal Foundry release or feed is published by this runner.
