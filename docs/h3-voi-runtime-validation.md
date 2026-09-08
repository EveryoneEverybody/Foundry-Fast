# Full Voi runtime validation

Nate's 2026-09-08 manual launch establishes **PARTIAL RUNTIME ACCEPTANCE**:
the installed full scenario loads, substantial BSP geometry is visible and
lit, and the H3 sky renders. This supersedes only the historical handoff's
runtime launch status. Object interaction, physics, each BSP and zone
transitions require their own results. Lighting remains deferred; Power25
produced no perceptible improvement and is not an accepted multiplier.

`tools/prepare_h3_runtime_validation.py` reads the historical handoff and its
hashed native receipts, verifies the source scenario and installed native tags,
and writes a new fixture report outside both kits. It does not author tags,
change placement flags, bake lightmaps or compile HSC. Fixture identity uses
source family/index, retains sparse palette mappings and includes an installed
tag snapshot hash. Observations require the exact scenario and fixture hashes,
an observer, a time with timezone, and specific runtime evidence. Build-only
evidence cannot produce a runtime pass. A visible crate does not establish
physical response, and passing a fixture never accepts its whole family.

```powershell
python D:\HaloRE\GitHub\Foundry-Fast\tools\prepare_h3_runtime_validation.py `
  --handoff D:\HaloRE\PortCensus\voi_full_scenario_20260908\morning-report.json `
  --h3-root D:\SteamLibrary\steamapps\common\H3EK `
  --reach-root D:\SteamLibrary\steamapps\common\HREK `
  --output D:\HaloRE\PortCensus\voi_runtime_validation_next `
  --fixture scenery:113 --fixture crates:882 --fixture machines:41 --fixture controls:0
```

Use a new output directory each time. To record runtime results, fill only the
checks actually observed in `observations.template.json`, remove untouched
template entries, and supply that separate file with `--observations`. Keep
captures and exact console queries with the evidence. `RUNTIME_TEST_PENDING`
can record an inconclusive attempt without calling it an object failure.

The first selected fixtures are:

| Fixture | Source → native placement | Position in world units | Notes |
|---|---|---|---|
| Old generator scenery | 113 → 54 | -68.9394, -8.10452, -1.49765 | BSP6; collision model exists; initial visibility attempt inconclusive |
| Cinderblock crate | 882 → 379 | 24.3655, -99.4547, -1.28459 | Near source crate 881; retained source bind pose, not decoded stored pose |
| Arms door | 41 → 13 | -4.25, -100.5, -1.5 | `factory_a_entry02`; 13 nodes, 100 frames at 30 fps |
| Control | 0 → 0 | -4.35, -99.2, 1.1 | `factory_a_entry02_switch`; scale 1.5 |

Control 6 (`factory_a_entry02_switch02`) is on the opposite side at
`-4.35, -101.8, 1.1`. Both controls and door 41 share source position group 2,
`tank_room_a_entry_buttons`. Initial group value is 0 and its authored flag
allows change only once. Reset the scenario before repeating the switch test.
Do not infer button usability or moving collision from the native shared group.

Of the 603 translated placements, source `not automatically` flags are retained
on 74 scenery, 453 crates, zero machines and one control. The remaining
2/35/21/17 placements are only automatic-flag candidates; zone/designer-zone
and other runtime conditions still apply. Unnamed explicit-spawn placements
must not be made automatic globally to compensate for deferred scripts.

All 19 authored zone masks remain unchanged, including `all = 255`. Thirteen
automatic switches are deferred, and native PVS/audibility indices remain -1.
The eight protected files, 986 Factory A files and 50 proof_box files are checked
against the existing preservation snapshot before and after this phase.
