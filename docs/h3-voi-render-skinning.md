# Voi sliding-door render skinning fix checkpoint

The H3 source, decoded IR, and generated Blender vertex groups all retain the
correct door-half ownership. Foundry's render vertex weld omitted skin attributes
from its comparison key. It merged coincident seam corners belonging to separate
moving bones, then kept the first corner's weights. Adding the exported bone
palette indices and weight bytes to that key fixes all 24 affected triangle
corners, corresponding to the 12 vertices corrected in the user's manual file.

Branch: `feature/h3-scenario-inspection`. Starting HEAD:
`bbb7ac23c96e43089d852442a89c4e0aa156ddc8`. The working tree was clean before this
change. The final committed HEAD and evidence hashes are recorded in
`D:\HaloRE\PortCensus\voi_door_render_skinning_20260908_01\checkpoint.json`.
This checkpoint is local; no release/feed update or remote CI run was requested.

The fix is in `export/virtual_geometry.py` and `export/vertex_weld.py`. Render
welding now compares skinning alongside position, normal, UV channels, lighting
UVs and vertex colors. The existing epsilon (`1e-4`), stable first-seen order,
weight normalization/quantization and non-render position-only weld behavior are
retained. The unchanged numeric weld implementation was extracted to allow tests
without Blender or ManagedBlam initialization.

This rule generalizes to weighted machine/device render models and other skinned
render geometry: corners with different exported deformation attributes are
distinct vertices. Intentional multi-bone blends remain intact. No rigid-part
heuristic, spatial side assignment, door-name special case, or single-bone
conversion is needed. Other device models have not received new runtime tests.

The reference archive is
`D:\MODS\Blender\port\voi\fixed_voi_door_arms_new_300ea1ebf524.zip`, SHA-256
`dc7ee5fa2b860a9724d6bfd4de8d674b30b322858ae3e0784dbdb17efe5a5212`.
Both saved meshes have 2,357 vertices and 1,600 triangles. Base positions, polygon
indices and UVs are identical. The files are saved on different animation frames
(102 and 145), so evaluated poses were not treated as an ownership comparison.

The saved group data refines the visual diagnosis: every vertex has one positive
influence in both files. Of 230 changed group records, 196 only add zero-weight
memberships, 22 change positive magnitudes without changing the owner, and 12
change the positive owner. Those 12 switch from `anim_voi_door_arms_a_02` to
`anim_voi_door_arms_a_01`. Incorrect ownership across a triangle's corners causes
the fence-like deformation; the saved bad vertices do not have two positive
blended influences. The translator fix preserves the source's weight of 1.0
instead of reproducing incidental manual paint magnitudes.

All indices below are zero-based. H3 indices are in source mesh 0's raw vertices.
IR indices also identify vertices in the fresh Blender mesh and corners entering
the exporter. Native corrected indices remain the same as the manual indices.

| Bad/manual/native vertex | H3 raw vertex | IR / Blender / export corner indices |
|---|---|---|
| 6 | 1882 | 3707, 3708 |
| 38 | 1689 | 3220, 3223, 3225 |
| 43 | 1687 | 3219 |
| 45 | 1762 | 3410, 3413, 3414 |
| 50 | 1760 | 3408 |
| 131 | 1775 | 3436, 3439, 3441 |
| 146 | 1684 | 3212, 3215, 3216 |
| 384 | 1878 | 3701, 3702 |
| 747 | 1804 | 3492 |
| 748 | 1805 | 3494, 3495 |
| 755 | 1796 | 3474 |
| 756 | 1797 | 3475, 3477 |

The source render tag is
`objects/levels/solo/040_voi/voi_door_arms_new/voi_door_arms_new.render_model`, SHA-256
`97a9b805ce9b09f75ac4c4fe231a28c67215b6adda2469f43a41f4a887aeda26`.
The pinned `blam-tags` decoder revision is
`5d0509fb75eadb96ac7774542ca0b2c10aed7b00`. Its `jms.rs` reads each positive raw
node weight and emits triangle corners. The bridge's `mesh_json` copies those
node sets; `BuildSession.build_mesh` creates corresponding Blender groups.
Neither source decoding nor Blender group authoring requires a change.

| Trace stage | Evidence |
|---|---|
| H3 render model | 2,356 raw vertices, 1,600 triangles; every vertex has one positive weight of 1.0 |
| Decoded IR | 4,800 deindexed triangle corners; all weights match source strip/part indices |
| Fresh Blender build | All 4,800 vertex group assignments match IR |
| Export before fix | 2,693 welded vertices; 24 corners inherit the wrong half's skinning |
| Export after fix | 2,703 welded vertices; zero corners change skinning |
| Native Reach before fix | 2,357 vertices; exactly the 12 manual vertices have wrong ownership |
| Native Reach after fix | 2,357 vertices; all 4,800 source corner weights match |

All native triangles were matched to source triangles by position, normal and
UV, independently of weights. The matching is unique and covers all 1,600
triangles. Native triangle indices/parts and UVs are unchanged. Skeleton nodes
including hierarchy/rest data, node checksum, regions, materials, markers and
compression bounds compare identically to the previously installed render tag.
Recompilation changes six decoded positions by at most `7.70e-8` native units
and 236 decoded normals by at most `0.000660` per component; these remain within
the recorded geometry comparison tolerances. The 12 weight-owner changes above
are the complete native skin delta.

`tests/fixtures/voi_door_render_skinning.json` contains 74 actual captured corners:
affected source triangles and their original first-seen weld representatives,
with source hashes and the H3-to-IR-to-native index trace. The six tests in
`tests/test_render_vertex_weld.py` reproduce the exact 24-corner failure when
skinning is omitted, preserve all owners with the fix, verify separation of the
door halves, preserve distinct intentional blends, and retain attribute seams,
epsilon behavior and stable duplicate ordering.

Validation used Blender 5.2.1, its bundled Python/NumPy, normal Foundry GR2 export,
Reach Tool import, and native XML readback. Both controlled Tool imports exited
0. They wrote only fresh `door_skinning_before_01` and `door_skinning_after_01`
namespaces under `levels/h3_port/040_voi`, referencing existing shader tags.
No collision, physics or animation payloads were exported. No lightmap job ran.

The isolated pure suite covered 44 modules: 43 passed initially. The bitmap
worker module encountered `PermissionError: [Errno 13] Permission denied` while
reading its temporary `result.json`; all 25 tests in that module passed when
rerun with a dedicated `TEMP`/`TMP`. All six new render tests passed. Existing
physics, interaction, scenario and lighting test modules passed unchanged.

```powershell
Set-Location 'D:\HaloRE\GitHub\Foundry-Fast'
& 'C:\Program Files (x86)\Steam\steamapps\common\Blender\5.2\python\bin\python.exe' -m unittest discover -s tests -p 'test_render_vertex_weld.py' -v
& 'C:\Program Files (x86)\Steam\steamapps\common\Blender\5.2\python\bin\python.exe' tests/run_pure_suite.py
```

Only this existing generated tag was replaced:
`D:\SteamLibrary\steamapps\common\HREK\tags\levels\h3_port\040_voi\full_scenario\objects\voi_door_arms_new_300ea1ebf524\voi_door_arms_new_300ea1ebf524.render_model`.

- Previous SHA-256: `3810102f87c5857f7fa8acd9ec249d7e55c7246437453970235b2523e1c56e2d`.
- Installed SHA-256: `5f1fecc0c8acb108aed920f98c7933867f3911f387d864497c54bb55fb9b4c99`.
- Backup and guarded rollback: `voi_door_arms_new.render_model.before` and
  `Restore-Render.ps1` in the evidence directory. Rollback was not executed.

All other 3,696 unique baseline files match their startup hashes, including
986 Factory A files, all 50 `proof_box` files, eight protected files, and the
remaining full-scenario assets. All six source tags, source scenario, cached IR
and manual archive remain unchanged. The current door animation graph hash
`ee91688e2a64114ddfdffcd8e436636760207e52781b1a21c18d37f89a0cf7af`
was preserved, including its pre-existing difference from the previous checkpoint.
The model, machine, collision and physics tags were not replaced. User Blender
files and installed add-on copies were not modified; the exporter correction is
in this branch and was used by the isolated builds.

Status: **RENDER_SKINNING_FIX_INSTALLED; NATIVE_WEIGHTS_MATCH_SOURCE**.
The user's manual corrected door already has visual acceptance. Live visual
acceptance of this newly generated and installed tag is **PENDING_USER_VISUAL_RELOAD**.
The earlier button, linked-machine, moving-collision, traversal and cinderblock
interaction passes remain recorded; this checkpoint does not repeat or broaden
those runtime claims.

The evidence directory is
`D:\HaloRE\PortCensus\voi_door_render_skinning_20260908_01`. Key records are
`blend-audit/manual-weight-diff.json`, `source-trace.json`,
`native-corner-trace.json`, `build-before/report.json`, `build-after/report.json`,
`native-corner-after.json`, `native-render-delta.json`,
`render-compatibility.json`, `installed-checkpoint.json`, `pure-suite.log` and
`bitmap-retest.log`. Scripts and captured pre-weld arrays retain the complete
reproduction and index trace outside the repository.
