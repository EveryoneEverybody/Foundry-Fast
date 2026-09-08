# Full 040_voi native scenario milestone

The isolated full-scenario target contains all nine authored BSP references,
eight structure designs, ten seams, one sky and nineteen source zone-set masks,
plus 603 native placements from 63 compiled object dependencies. It is installed
at `HREK/tags/levels/h3_port/040_voi/full_scenario/full_scenario.scenario`.
Status as of Nate's 2026-09-08 manual test: **PARTIAL RUNTIME ACCEPTANCE**.
The full native scenario launches; substantial environment geometry is lit and
the converted H3 sky renders. Individual object behavior, all nine BSPs, zone
transitions and physics remain unaccepted until tested. Shiny/overexposed
surfaces, localized open-edge defects and dark distant portal cliffs remain.

The historical overnight handoff is
`D:/HaloRE/PortCensus/voi_full_scenario_20260908/morning-report.md`, with exact
commits, hashes, source/native identities and blockers in `morning-report.json`.
Its `NOT_TESTED` and not-yet-runnable statements predate Nate's manual launch
and are superseded by the runtime status above. Keep its native inventories
and immutable receipts as evidence. Current runtime fixture preparation is
documented in [h3-voi-runtime-validation.md](h3-voi-runtime-validation.md).
No push, release or feed update was performed.

Factory A lighting fidelity: **DEFERRED / technically responsive material-power
path but no meaningful visible runtime improvement from diagnostic Power25.**
The four diagnostic BSP010 lighting files were restored to baseline. Nate's
warm self illumination 3 and cool 1 shader bytes are preserved. All 986 Factory A
files, 50 proof_box files, and eight explicitly protected files match the
post-restoration snapshot, including the experimental H3EK
`levels/solo/030_outskirts/shaders/outtree_bark.shader`. The accepted colored sky
and six breakable office-glass placements remain protected fixtures.

## Native source accounting

Counts are source / translated / deferred. Distinct source palette indices
remain distinct even when they refer to the same source tag.

| Family | Palettes | Placements |
|---|---:|---:|
| Scenery | 43 / 20 / 23 | 203 / 76 / 127 |
| Crates | 75 / 33 / 42 | 1029 / 488 / 541 |
| Machines | 15 / 7 / 8 | 70 / 21 / 49 |
| Controls | 4 / 3 / 1 | 18 / 18 / 0 |

The dependency census contains 136 unique roots: 63 native compiled, 45 deferred
by source planning, and 28 deferred by native validation. Absent source palette
indices account for six scenery and nine crate placements within the deferred
counts. Every omitted dependency and placement retains its reason in the IR.

All 115 source object names, 13 device groups (including duplicate names), four
player starts and 168 static trigger volumes round-trip through native tags.
Eighteen of 22 source control/machine relationships survive: controls 0 and 6
share position group 2 with source machine 41, becoming native controls 0/6 and
machine 13. The arms-door graph has 13 nodes and 100 frames at 30 fps from 101
source JMA samples. Interaction, motion and physical response remain untested.

The authored `all` zone retains mask 255. Later authored zones selectively
include BSP008; no synthetic mask 511 is introduced. All fifteen designer-zone
tables preserve supported palette memberships. Source PVS/audibility and five
cinematic zones remain evidence; native PVS/audibility indices are -1.

Two object-relative triggers are deferred. Reach reopened zero automatic
zone-switch records after authoring all thirteen source records. The runner's
explicit `--defer-zone-switches` mode retains every source switch and remapped
static-trigger identity in its report, leaving the native table empty. Normal
validation remains strict unless that mode is selected. Automatic zone
transitions are not claimed.

## Shared authoring and validation

`scenario_ir.py` retains complete source identities separately from native
generation. `object_ir.py` represents shared non-unit dependencies. The worker
reconstructs decoded authoring through normal Foundry, GR2/sidecars and Reach
Tool. Flags and enums match by name. Native variant regions, permutations and
probabilities are verified after reopening.

Physics mesh region/permutation identities enter the normal export. Ambiguous
shape/body associations are deferred. Native loose mass, motion, damping,
inertia-scale and material fields match by node/region/permutation identity.
Tool rebuilds shapes and resources; effective runtime mass and collision remain
unverified. No H3 runtime resources are copied.

Of 404 source crate placements with packed stored poses, 217 translated
placements use source bind pose (`STATICIZED_MVP`). Object functions, damage
states, attached effects/sounds and non-device animation remain deferred. The
native test profile uses Reach assault rifle, magnum and sprint defaults;
source H3 gameplay/profile data remains in the IR.

`run_h3_scenario_objects.py` shares the environment target lock and exact-hash
ownership manifest. Material failures are isolated per object. Completed
same-plan receipts can reuse compiled objects only after output hashes and
complete source accounting match. Explicit retries retain the other results.
Normal environment material validation stays strict.

`audit_h3_native_dependencies.py` reads generated references reachable from the
scenario. Stock target defaults must exist and are reported separately; they
are not recursively translated. Imposter placeholders are allowed only for the
exact owning asset under a verified `never` policy or zero instances.

- 80 focused tests passed in five isolated processes. The prototype workflow
  now includes the native-object suite; no CI run was triggered.
- All 63 native object chains reopen and export through Reach Tool XML.
- The 603-placement scenario passes identity, transform, group, start,
  designer-zone and streamed Tool XML validation, with explicit switch deferral.
- The dependency audit opens 1,315 reachable generated tags and checks 3,836
  existing reference edges. One required dependency is missing:
  `full_scenario_faux_lightmap.scenario_lightmap`. Seventy-three unused native
  imposter references are classified separately.
- The environment import exits 0, but strict geometry validation fails on 76
  diagnostics: 33 open edges, 31 degenerate triangles and 12 overlaps. Source
  collision was not deleted to suppress them.
- BSP7 instance 974 (`?+rocks_gun_single11`) has one scale mismatch, affecting
  three basis-vector checks: source 1.0001447200775146 becomes native 1.0.
  Tolerances were not widened. Final BSP/design/seam hashes match this checkpoint.

The 28 native deferrals comprise eleven ambiguous physics associations, four
body-identity mismatches, six insufficient/invalid physics shapes, four roots
with unsupported first-person shader misc semantics, two scenery assets with
unverified cubemap readback, and one unsupported MCC Moa PBR asset. Source-plan
blockers retain missing-tag, material-function/group/indexed-bitmap and bounded
physics-adapter reasons.

Sound scenery, effect scenery and light volumes were inventoried and deferred.
No unit, biped, vehicle, AI, squad, HSC, character-animation or vehicle-physics
translation was added. The handoff includes the complete remaining-family census.

## Next acceptance step

The installed full target has a manually confirmed launch. Lighting is
**DEFERRED / sufficiently functional for continued scenario and object work**.
Power25 is not an accepted conversion multiplier. The missing Faux dependency
and strict geometry diagnostics remain recorded; they are no longer assumed
to prevent launch. Do not restart lightmapping as an object-validation gate.

Use this Tag Test console command:

```text
game_start levels\h3_port\040_voi\full_scenario\full_scenario
```

Test a source Voi switch/arms-door pair and cinderblock physics, then source zone
visibility and traversal. Tool/ManagedBlam checks do not establish runtime acceptance.
