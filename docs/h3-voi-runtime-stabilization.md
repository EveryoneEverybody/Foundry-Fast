# Voi runtime stabilization

Nate accepted prototype 1.9.49 for core BSP conversion at `789848bd1fb7ab88d6507a6b792d298d030eefb8`. Preserve the working collision, ladders, breakable glass, materials and sunlight. The earlier 1.9.48 proof_box runtime acceptance remains valid.

This pass is limited to visible H3 sky rendering, the cause of missing BSP010 tunnel illumination, Tag Test seam/leaky/duplicate-triangle diagnostics, and classification of missing Keyship/Voi portal content as sky versus scenario/cinematic resources. AI, HSC and general scenario-object conversion remain outside scope.

Reported symptoms: sunlight works; distant Voi cliffs and their glowing elements are visible in a dark sky; tunnel light textures are visible but do not adequately illuminate the tunnel. These observations are runtime evidence, separate from the previous Tool/Faux/native-readback checks.

The installed scenario tag differs from the packaged 1.9.49 hash. Preserve and inspect that edit before any tag write. The remaining 979 generated files and all 50 proof_box outputs match the preserved build. The local acceptance receipt, runtime-log copies and subsequent investigation live under `D:\HaloRE\PortCensus\voi_runtime_stabilization_20260907`. The existing native archive remains the immutable build backup.

The pinned H3 JMS bridge writes `color: None` for every decoded sky vertex. The source sky has eleven color-authored meshes, including the skydome gradient. `sky_attributes.recover` checks every source triangle corner against the accepted position, normal, UV and material before restoring its linear RGB. The existing Foundry mesh writer now exports sixteen source sky regions/permutations separately, preserving the five groups without authored colors. Tool readback verifies all 4,134 unique authored RGB values; these expand to 10,677 vertices in the triangle-expanded intermediate mesh. Geometry, materials, texture pixels and the 200 sky-light records are retained.

`runtime_sky.py` reuses the compiler's Foundry construction, sky-light authoring, GR2/sidecar export, Tool journal and native world validation. It backs up the existing sky and scenario, repairs only the generated scenario's sky reference, rejects writes outside that sky and scenario, and emits a separate sealed plan containing the recovered attributes. The accepted parent plan remains unchanged. Reach Tool marks all compiled sky meshes color-enabled, even those with no source color attribute; the report distinguishes its zero defaults from recovered H3 colors. The `converted vmf for sky is wrong` Tool diagnostic is retained. Readback shows the default dual-VMF coefficients, sunlight array and all sky-light records are identical to the accepted build; visible acceptance is still Nate's check.

Nate requested a `low` bake before changes to the tunnel lighting converter. `runtime_bake.py` operates on the existing owned native environment and reuses normal Foundry Faux. It does not reconstruct geometry or lights. It validates source/native lighting and world relationships before and after the bake, preserves every current tag, checks process exits and logs, and records output hashes. The installed HREK preset differs from `direct_only` as follows:

| Preset | Starting photons | Final-gather pitch | Maximum gather samples |
| --- | ---: | ---: | ---: |
| direct_only | 0 | 0 | 0 |
| low | 1,800 | 4 | 126 |

The existing 215 static-light placements and twelve unique positive emissive rows are present before this comparison. Glowing fixture textures alone do not prove a bake contribution; the direct-only job did sample surface lights, but omitted indirect illumination. The low comparison keeps the converter values fixed. A runtime comparison is required before attributing the tunnel darkness entirely to missing bounce lighting.

Both operations accept a JSON config with `addon`, `h3_root`, `reach_root`, `namespace`, `accepted_plan`, `parent_manifest`, and a new `run` directory. Bake also takes `scenario`, `zone_set`, `quality` (`low` or `direct_only`) and `threads`. Sky can take the explicitly pinned `sky_source_xml_sha256` and `preserved_scenario_sha256` for evidence extensions or an already reviewed scenario edit. `preserved_external_files` records exact hashes of user additions: they must remain unchanged and are excluded from compiler ownership. Unexpected edits still reject the operation.

```powershell
.\tools\Run-VoiRuntimeStabilization.ps1 -Action Bake -Config 'D:\HaloRE\PortCensus\voi_runtime_stabilization_20260907\low-bake-config-next.json'
```

The standalone runner uses installed Blender 5.2.1, propagates Python failures, and requires a completed report before printing the Tag Test command. A new comparison needs a new run directory and the manifest matching the current owned outputs. It never reruns the main multi-BSP importer.

The persisted diagnostics are distinct from map-disposal texture-resource leaks:

| Diagnostic | Evidence and disposition |
| --- | --- |
| 2 seam-leak reports | Stored by `connected_geometry_seam_filler` at the active 000/010 doorway near `(-11.5,-104.5,-0.45)`. Native seam ownership and triangle winding validate. Reach's closure diagnostic remains unresolved; no opening is filled or neighboring BSP added. Diagnostic marker arms are not measured geometric gaps. |
| 6 leaky-mesh reports | Four BSP010 placements: 42, 312, 260 and 292. Original collision edge tables have no missing left/right owner; reconstructed geometry includes coincident/shared edges with valence three. This identifies a topology investigation, not permission to remove collision. The associated native leaky-connection diagnostics remain present. |
| 18 import duplicate-triangle warnings | Sixteen matching fence duplicates exist in original source render object 127, definition 100, placement 502, using `metal_out_fence.shader`. The two roof-widget warnings need a more exact export correspondence; they are not declared repaired. |
| 2 lightmapper-preparation duplicate messages | Preserved separately from import warnings, with their mesh/triangle identifiers and coordinates. No triangle deletion is performed. |

`source-tool-diagnostics.json`, `native-persisted-diagnostics.json` and `duplicate-triangle-source-correspondence.json` preserve source identities, placements, matrices, geometry and exact Tool provenance. They are local evidence, not proprietary CI fixtures.

Missing distant content is classified from the actual scenario palettes/placements and stock H3 lighting script: scenery placement 158 `truth_ship` references `objects/cinematics/forerunner/forerunner_ship/forerunner_ship.scenery`; machine placement 0 `ark` references `objects/skies/ark/ark.device_machine`; machine placement 1 `storm` references `objects/skies/storm/storm.device_machine`; scenery placement 6 `clouds_ark` references `objects/skies/clouds_ark/clouds_ark.scenery`. The `objects/skies` directory does not make these part of the scenario sky palette. The H3 script explicitly applies cinematic lighting to these objects. Their conversion remains outside this pass.
