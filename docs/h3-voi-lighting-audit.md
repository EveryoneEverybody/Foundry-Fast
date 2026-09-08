# BSP010 lighting audit and controlled comparison

Nate reports that the low bake only modestly improved the dark interior. The newer runtime screenshots show the sky/clouds rendering and interior strips glowing, while the surrounding room remains dark. This does not establish whether generic-light power, omitted scenario lights, surface emission, or another target behavior dominates the remaining difference.

The audit begins from `86ed2a45a13f3e17957738f187042a1182838210` on `feature/h3-scenario-inspection`. Its working tree was clean. Prototype 1.9.49 remains runtime-accepted for core BSP conversion; collision, ladders, glass, materials, sunlight and the 1.9.48 proof_box fixture remain regressions. No source converter or source recipe is changed in this pass.

`tools/audit_h3_environment_lights.py` compares the preserved H3 lighting-info XML, accepted authoring IR and freshly exported native Reach lighting-info XML. It checks every definition and instance, keeping the raw records and field-level results. It uses the original accepted source snapshot; installed bark-shader edits are not consulted. The local evidence directory is `D:\HaloRE\PortCensus\voi_bsp010_light_audit_20260907`.

All fourteen BSP010 static instances and all three definitions match. All are spots:

| Definition | Instances | Source = native intensity | Shape | Hotspot / cutoff (degrees) | Attenuation enabled |
| --- | ---: | ---: | --- | --- | --- |
| 0 | 9 | 4 | rectangle | 24.8000 / 53.1000 | neither near nor far |
| 1 | 2 | 40 | circle | 20.6000 / 48.9000 | neither near nor far |
| 2 | 3 | 2 | circle | 26.5000 / 100.7999 | far: 0.936–2.78 world units |

Color, aspect, position, forward/up, attenuation bounds and enable flags are retained. Definitions 0/1 contain far bounds 0.8–2, but those bounds are disabled; treating them as a 2-unit cutoff would misread the source. H3 angular fields are converted from radians into Reach's degree authoring fields. Shape is mapped by name because the H3/Reach enum order differs. Reach's version marker is not an attenuation flag.

All native instances have `default ligthmap light`, bounce control 1, no screen-space specular override, no fade/volume override and no light/shader/gel/lens-flare references. H3 generic instances have no separate bounce field. Bounce 1 and hotspot falloff speed 1 are explicit Reach defaults, supported by the current Foundry writers and [Reach authoring parameter inventory](https://c20.reclaimers.net/hr/guides/json-parameters/), not recovered H3 values. The JSON marks this distinction. Forward/up use Foundry's X/Z basis convention; no viewport light or extra Euler transformation is involved.

The current Foundry lighting-info writer uses an intensity divisor of 1 and saves/reloads its placeholder rows before writing to avoid Reach postprocessing the authored intensity unexpectedly. Its historical spot divisor is deprecated. Neither that old divisor nor Blender's energy conversion is evidence for an H3-to-Reach intensity multiplier. Equal preserved numbers establish structural mapping, not equal photometric response.

## Omitted scenario light placements

The source scenario contains four light-volume rows and four palette entries. Display labels repeat `type` three times; the audit reads the **short block index** as palette identity, separately from the legacy object type and volume shape. A dictionary keyed only by display name would lose this relationship.

The scenario also references `resources/040_voi.scenario_lights_resource`. Its four light rows match all 39 ordered fields per row in the embedded scenario, and its palette matches exactly. These are the same authored placements, not four additional lights. The referenced `scenario_structure_lighting_resource` exposes no fields in H3 Tool XML; the pinned H3 schema declares only root padding. `source-split-light-resources.json` records this independent check and both source hashes.

The read-only Rust example `lighting_spatial` exports the source BSP's packed 3D nodes, planes and leaf clusters. H3 Tool's XML leaves the packed node data blank, so XML alone is insufficient for this query. The pinned blam-tags `collision_verify::children/descend_point` implementation supplies the layout and plane-side convention. All fourteen static origins and all four scenario volume origins descend into valid BSP010 cluster leaves. This establishes spatial membership; it does not fabricate manual BSP/light-volume activation flags.

| Source row | Palette | Position (world units) | BSP010 cluster | Nearest positive-emissive source fixture |
| --- | ---: | --- | ---: | --- |
| 0 | -1, unbound | (-0.276547, -96.5801, 2.60991) | 6 | 3.7540 units away; no bound light tag |
| 1 | 3 | (6.65827, -95.3604, 0.282168) | 6 | `?lightfix_f_blue_196`, placement 378, 0.7204 units |
| 2 | 3 | (20.6312, -95.4715, 0.616386) | 11 | nearest is 2.9656 units away; no close fixture match |
| 3 | 3 | (-2.99755, -95.7057, -0.146525) | 6 | `?lightfix_f_blue_195`, placement 371, 0.2785 units |

All three bound rows reference `factory_arm_blue_a.light`: constant intensity 2, RGB (61,60,135)/255, maximum distance 2 world units, with the H3 overhead-A gel bitmap. Function headers are decoded only as verified non-ranged constants, using pinned blam-tags semantics; no wall-clock sample is taken. Per-placement sphere/frustum shape, target point, FOV and cutoff overrides are retained separately because their precedence over the tag fields has not been established.

The `gel_factory_arm_overhead_b.light` (constant intensity 100), `gel_factory_arm_overhead_a.light` (10), and `voi_temp_hack.light` (0.3) palette entries have **no bound placements** in these scenario rows. They cannot be assigned to fixtures by palette order or name. All original volume fields, including zero lightmap scale and unset manual BSP membership, remain in the report. Zero scale is not proof of zero runtime contribution: the engine's zero/default behavior is still unverified.

The nearest-fixture search uses world-transformed source triangles from 151 positive-emissive mesh/material groups, with exact placement and material provenance. It measures distance to triangle surfaces, not just centroids. Spatial closeness supports a candidate association; it does not prove authored light ownership. Two omitted blue lights may explain localized missing fill. Their limited count and locations do not establish the cause of the whole dark interior. No scenario light placement is converted here.

## Controlled test

The passing structural audit authorizes a diagnostic power scale. Only BSP010's three native definition intensities change: 4→40, 40→400, 2→20. Its fourteen instance transforms, color, shapes, flags, ranges, angles, bounce behavior and emissive material rows remain unchanged. The accepted source plan is immutable; the modified IR exists only as an explicitly labelled diagnostic view.

The test keeps the parent's exact `low` preset, one worker and **all-BSP** bake scope. Baking BSP010 alone would change photon allocation and inter-BSP transport, introducing another variable. Before Faux, an independent XML readback verifies that intensity is the only lighting-info change. Full native world/lighting checks run before and after. Every prior tag is backed up; output hashes guard user additions and core BSP tags. This is a calibration experiment, not an approved conversion rule or runtime success claim.

Reproduction (use a new run directory and the manifest matching the current state):

```powershell
python .\tools\audit_h3_environment_lights.py --config 'D:\HaloRE\PortCensus\voi_bsp010_light_audit_20260907\audit-config.json'
.\tools\Run-VoiRuntimeStabilization.ps1 -Action Bake -Config 'D:\HaloRE\PortCensus\voi_bsp010_light_audit_20260907\scale10-low-config.json'
```

Completed configurations are evidence and intentionally refuse to overwrite their report folders. The comparison receipt captures both native lighting states. `tools/switch_environment_bake.py --receipt <receipt.json> --variant baseline|scale10` verifies the entire current ownership snapshot and every replacement hash before switching. `--dry-run` performs the preflight without writes. BSP geometry, collision, shaders and sky cannot be changed by this helper. Exit Tag Test before switching and reload the scenario afterward.

Runtime test command remains:

```text
game_start levels\h3_port\040_voi\factory_a_env\factory_a_env
```

Compare the same interior position, camera direction and exposure conditions against the captured low baseline. A large improvement would implicate generic-light magnitude; little improvement would constrain that hypothesis without proving scenario lights or emissive conversion are correct. Glowing fixture appearance alone does not establish illumination ([H3 baked-lighting workflow](https://c20.reclaimers.net/h3/guides/map-making/baked-lighting)). Do not adopt the 10× scale as a source semantic merely because it looks brighter.
