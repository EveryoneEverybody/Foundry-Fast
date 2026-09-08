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

```powershell
python -m unittest discover -s tests -p test_h3_physics_association.py -v
```

The tests cover same-node bodies, nested containers, exact list coverage, cycles,
shared/unowned shapes, source and decoder drift, inverse identities, reordered
native bodies, misassigned native shapes, and native material identity changes.
