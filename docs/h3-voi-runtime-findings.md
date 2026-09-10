# Voi runtime continuation findings — 2026-09-08

Status remains **PARTIAL RUNTIME ACCEPTANCE**. The scenario-only origin repair
restored the selected arms door and generator to visible runtime objects.
Control 0 changes door 41 through the real source position group in a fresh
runtime session. Compilation totals remain 603 placements from 63 object roots;
no additional asset or physics coverage is claimed.

Evidence is under
`D:\HaloRE\PortCensus\voi_runtime_validation_20260908`.
`runtime-observations.json` records supported computer-use observations with
screenshot hashes. `observed-01/runtime-validation.json` binds them to the
installed scenario and all 1,511 generated tags. `session-report.md` and
`session-report.json` contain the final branch, commit and preservation audit.

| Source fixture | Runtime passes | Still pending |
|---|---|---|
| Scenery 113, old generator | Visible in `ware` | Model/material comparison, exact transform, variant, collision |
| Crate 882, paired cinderblock | Visible with 881 | Material/transform comparison, collision, push/shot response; stored pose is staticized |
| Machine 41, `factory_a_entry02` | Visible; queried closed 0/open 1 | Exact transform, intermediate animation/timing, moving collision |
| Control 0, `factory_a_entry02_switch` | Visible; console-driven linked-machine response | Player-operated use and exact transform |

No complete fixture is globally accepted. Player teleport attempts returned to
a start/respawn view and did not establish a controlled interaction test. They
are inconclusive, not proof of broken crate physics. The two door poses prove
an articulated position response; full animation timing remains unmeasured.
The source `tank_room_a_entry_buttons` group allows only one change, so repeat
tests must start from a fresh scenario. Of 18 native-readback relationships,
one has this bounded live control-driven proof; the source total is 22.

## One-material specular audit

`shader-specular-audit.json` covers source
`levels/solo/040_voi/shaders/metals/metal_floorplate_a_01.shader` and native
`levels/h3_port/040_voi/full_scenario/shaders/metal_floorplate_a_01_f228dd51.shader`.
Both select `specular_mask_from_diffuse`; native readback also reports
`two_detail`, `two_lobe_phong`, and dynamic environment mapping.

The original extracted 384 × 384 RGBA pixels exactly equal the native input
TIFF pixels. Alpha spans 16–163 with no white pixels. Decoding the compiled
native bitmap gives alpha 18–162, no white pixels, mean absolute difference
0.618/255 and correlation 0.99828 with the original. Thus this material does
not have lost diffuse alpha or an all-white specular mask. A matched H3/Reach
BRDF or radiometric comparison is still needed to explain overbrightness.
No shader, bitmap, lightmap or intensity change was installed.

## Geometry and sky provenance

`geometry-provenance-audit.json` proves four BSP7 duplicate instance pairs
already have identical H3 definition IDs and bit-exact transforms:
481/535, 482/536, 483/537 and 484/538. These are source-authored duplicate
warehouse-support placements. They do not classify the 76 existing Tool
topology occurrences or identify Nate's visible holes. No geometry was deleted
or repaired. BSP7 instance 974 still has three strict basis comparison failures
associated with source scale 1.0001447200775146 becoming 1; normalization by
Reach is not yet proven and tolerances remain unchanged.

`sky-cliff-fog-audit.json` identifies source groups 13 `crater` (4,308 triangles),
14 `mountain` (857) and 15 `terrain` (3,139) and their exact material slots.
They contain no authored vertex-color attribute. The current native render
model contains Tool-default black color on those groups. Authored colored
groups still pass exact RGB multiset readback. Default black is not evidence
that H3 authored black cliffs, nor does it prove Reach uses that color in the
active shader path. The portal-camera-to-triangle subset is not established.

H3 references `voi_atmosphere.sky_atm_parameters`; its settings include
`basic_haze`, `kilimanjaro_fog`, `distant_mountains` and `rain`. The H3 scenario
palette selects indices 0 and 3. The native scenario has an empty atmosphere
palette, no old-atmosphere reference and no atmosphere-globals reference.
This is a proven data gap. A stock Reach `.atmosphere_globals` example contains
fog-sheet and underwater settings, so copying that tag alone does not establish
a replacement for all H3 scattering settings. Reach-native mapping, actual
shader default-color consumption and a matched H3 portal view remain open.
The existing sky is unchanged.

## Reusable object blockers

`blocker-audit.json` retains exact historical reasons and upstream errors for
all 73 unresolved roots. Populations are potential affected source placements,
not guaranteed unlocks. Its classification refines the historical report:

| Cause | Roots | Source placements |
|---|---:|---:|
| Missing source files | 10 | 218 |
| Shape/body association | 11 | 134 |
| Native/source body identity | 4 | 71 |
| Capsule/constraint support | 14 | 68 |
| Shader functions/externs | 14 | 64 |
| Non-positive sphere radius | 5 | 48 |
| Shader misc semantics | 4 | 47 |
| Halogram shader | 2 | 21 |
| MCC PBR semantics | 1 | 17 |
| Indexed bitmap layout | 5 | 7 |
| Other exact reasons | 3 | 3 |

The pallet alone affects 179 placements. Its source `pallet_change color.bitmap`
is missing; treating the decoder's missing metadata as an indexed-layout error
hid that primary cause. The bitmap planner now preserves upstream decoder
errors before testing layout. The missing source asset remains a blocker.

`physics-association-audit.json` retains explicit rigid-body shape types/indices
for 34 roots. The 42-placement jersey barrier has ten polyhedra and eight
bodies sharing node 0, differentiated by region/permutation; one list owns
polyhedra 3/8/9. Node-only matching cannot represent that association. A shared
adapter needs proven decoded-shape identity, list ownership and native body
readback before using those references. Source mass/damping values remain in
the evidence; effective runtime mass is not accepted. No physics ownership or
radius rule was invented, and no new physics rule was installed.

The next runtime gate is an accessible player interaction fixture: cinderblock
push/shot response, normal button use and moving door collision. The next
coverage candidate is explicit physics shape/body association with source
indices preserved through decoding and verified native region/permutation
construction. Units, vehicles, AI, HSC conversion and lighting remain deferred.
