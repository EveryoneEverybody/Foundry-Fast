# Source-indexed physics shape ownership

`SOURCE_INDEXED_PHYSICS_SHAPE_BODY` replaces the node-only ownership check.
Several source bodies can share a node while belonging to different regions and
permutations. Each decoded shape now retains its source table/type/index, body
index, full body identity and reference path through list/MOPP containers.

The adapter admits the pinned `blam-tags` decoder
`5d0509fb75eadb96ac7774542ca0b2c10aed7b00`. Its `jms.rs` primitive readers
preserve table order. A complete count and ordered name/material match are
required before associating the legacy decoded payload with source indices.
The existing worker verifies source and payload hashes before this step.
Changed decoders, missing/reordered shapes, invalid list partitions, cycles,
unowned leaves and repeated/shared ownership are rejected. Node identity is
checked against the selected body after following its explicit shape reference.
Inverse region/permutation body lists must agree with the forward body fields.

Foundry physics mesh names carry stable `h3_<shape_type>_<source_index>` labels.
Tool can reorder native bodies and shapes: the native check resolves the labels,
expands native containers, then compares each leaf's material and complete body
identity. A matching body count alone cannot pass. Loose mass, damping and other
admitted authoring fields are copied only after the ownership check, then checked
again on reopening. No source Havok resource bytes, pointer values or mass guesses
are used. Capsule/constraint, body-identity and nonpositive-radius work remain
separate rules.

The first two native proofs are the medium cardboard box (2 bodies, 2 boxes,
17 source placements) and jersey barrier (8 bodies, 10 polyhedra, 42 source
placements). Jersey polyhedra 3/8/9 belong to source body 3 through list 0;
their identity is `jersey_barrier / front / minor`. Both compiled through normal
Foundry/Reach Tool and passed independent native leaf ownership readback.
This proves native reconstruction for these roots; their runtime status is
`RUNTIME_TEST_PENDING`.

Evidence: `D:\HaloRE\PortCensus\voi_physics_association_20260908_01`.
`source-association-audit.json` also verifies all 11 association-blocked source
roots (134 placements) and all 50 previously compiled roots with decoded physics.
`readback-01/report.json` retains native indices and the exact two native hashes.
The existing 603-placement main scenario is unchanged by these isolated proofs.

After those two proofs, all 11 previously association-blocked roots compiled
through the same rule. Native readback verified 28 bodies and 50 leaf shapes,
before copying loose body fields and again after reopening. This admits 134
source placements: 14 scenery and 120 crates. No capsule, constraint, invalid
radius or unresolved body identity was silently admitted.

| Newly compiled root | Source placements |
|---|---:|
| Large open cardboard box | 25 |
| Medium cardboard box | 17 |
| Small cardboard box | 9 |
| Jersey barrier | 42 |
| Crash cart | 1 |
| Large radio | 1 |
| Desk telephone | 10 |
| Armory shelf | 2 |
| Closed armory shelf | 8 |
| Cart trailer | 15 |
| Smashed curved monitor | 4 |

The bulk receipt is
`bulk-01/native-build/object-build/runs/20260908-134701-682d9c65/physics_association_02_build_report.json`
under the evidence directory. The newly generated objects use
`levels/h3_port/040_voi/physics_association_02`; their interaction behavior remains
`RUNTIME_TEST_PENDING`.

The separately named `physics_coverage_01` scenario integrates those objects
without rebuilding geometry or lighting. `coverage-readback-02/report.json`
verifies 737 placements: 90 scenery, 608 crates, 21 machines and 18 controls.
Deferred counts are 113, 421, 49 and 0 respectively. All 603 original placements
match the original native XML after removing only outer display index/name;
original palette paths match and native indices are separately checked. All
non-coverage sections, including BSP references, starts, zones, machines,
controls and device groups, are unchanged. The main remains 603 placements.

The first comparison stopped because its allowed-section list incorrectly used
`crates palette`; the actual schema field is `crate palette`. The original
failure is retained in `coverage-01/report.json`. Corrected read-only validation
passed on the same candidate bytes, SHA-256
`8591c234b1a11e4dbaec71390f24fbd4480044633402e7b50d3e0319a514308e`.

TagPlay loaded this exact candidate at `intro`; read-only queries returned
player health 1.0, deathless false and zone index 0. This is a load check only.
The original main was loaded again afterward, its two source startup volume
disables reapplied, and the console closed. Runtime captures 08–12 and the final
session report are in
`D:\HaloRE\PortCensus\voi_player_interaction_20260908_02`.

To load the installed candidate in TagPlay:

```text
game_initial_zone_set intro
game_start levels\h3_port\040_voi\physics_coverage_01\physics_coverage_01
```

After loading, before entering Factory A:

```text
(kill_volume_disable kill_all_lakebed_a)
(kill_volume_disable kill_bfg_cin_start)
```

Repeat both startup calls after any map reload/revert. The candidate retains
source explicit-spawn flags; a placement count does not mean every object is
automatically present. Scripts, automatic zone switches, PVS and audibility
remain deferred.

Installed stock Reach counterparts were inspected read-only through their
actual object/model/physics references. Jersey crate and scenery share one
native physics model with four bodies; H3 has eight. The medium cardboard box
has two bodies in both games but different node/region identities. Reach's
armory shelf has one body and H3's has two. Those differences are retained;
Reach body layouts do not replace explicit H3 shape ownership.

Stock body mass, inertia scale and damping fields can also read zero, supporting
the distinction between loose authored fields and effective runtime behavior.
This is not a measurement of effective mass or proof of behavior parity.
`reach-counterparts-02/report.json` records the layouts and verifies all ten
stock files unchanged.

```powershell
python -m unittest discover -s tests -p test_h3_physics_association.py -v
```

The tests cover same-node bodies, nested containers, exact list coverage, cycles,
shared/unowned shapes, source and decoder drift, inverse identities, reordered
native bodies, misassigned native shapes, and native material identity changes.
