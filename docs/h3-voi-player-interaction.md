# Voi player interaction fixture

The actual player can remain at `factory_a_entry02_switch` with normal health
and `cheat_deathless_player = false` once the original mission's startup
kill-volume settings are applied. The control displays **Hold [E] to open door**.
The user subsequently confirmed normal button activation, door animation,
blocking by closed doors and traversal through open doors. The follow-up manual
test confirms that collision follows moving panels, the panels block the player,
and the open part of the doorway remains passable during animation. Cinderblocks
respond to shots, move and collide with each other.

| Selected door check | Runtime result | Basis |
|---|---|---|
| Normal player button use | RUNTIME_PASS | User manual test |
| Player-driven control → group → linked machine | RUNTIME_PASS | User manual test; subsequent control/machine queries both 1 |
| Door animation | RUNTIME_PASS | User manual test; duration and node participation not measured |
| Fully closed door blocks player | RUNTIME_PASS | User manual test |
| Fully open door permits passage | RUNTIME_PASS | User manual test |
| Player traversal | RUNTIME_PASS | User manual test |
| Collision follows moving panels and blocks player | RUNTIME_PASS | Follow-up user manual test |
| Open aperture passable during motion | RUNTIME_PASS | Follow-up user manual test |
| Crate collision with its pair | RUNTIME_PASS | User reports blocks bump each other |
| Crate shot response and rigid-body motion | RUNTIME_PASS | User reports blocks move when shot |

The follow-up observation is
`D:\HaloRE\PortCensus\voi_player_interaction_20260908_02\door-player-observation.json`.
It retains the user's exact statement and binds it to the unchanged tested
scenario copy and source/native fixture indices. A live query after that test
returned control 1, machine 1, deathless false and zone index 2 (`faa_lakea`).
This accepts the selected fixture checks, not every translated door or zone.

After `game_revert`, the source startup calls and actual-player teleport to
`diag_crate` reached the crate area without enabling deathless. The fresh replay
and post-test door endpoints are captured under the same follow-up evidence
directory. `moving-collision-and-crate-observation.json` records the subsequent
manual collision and shot passes with the exact statement, input, scenario hash
and fixture indices. The selected player control → group → animated machine →
moving collision → traversal chain and crate shot-response chain are runtime
proven. This does not accept scenery collision or every translated object.

Opening duration, all-node participation, repeat-use/reset semantics, crate
player contact, settling and create-at-rest behavior remain unmeasured. Stored
orientation fidelity remains `STATICIZED_MVP`; effective mass is not measured.
The observed shot response is not grounds for replacing the loose authored mass
value or changing physics.

## Why the earlier teleports appeared to fail

`H3EK/data/levels/solo/040_voi/scripts/040_voi_mission.hsc:4128-4129` disables
`kill_all_lakebed_a` and `kill_bfg_cin_start` at startup. Its SHA-256 is
`cb95588b12dfa128597f5c91032f59420e006d8c7c3006d2738a8434f1dcff04`.
The lakebed cleanup routine temporarily enables the first volume at line 1245
and disables it again at 1248. The second is used during the BFG cinematic
transition at 3171 and 3181.

Both trigger transforms are retained exactly in Reach. Source volume 144 maps
to native 142 (`kill_all_lakebed_a`); source 168 maps to native 166
(`kill_bfg_cin_start`). At the switch, `volume_test_players` returns true for
the first and false for the second. The first volume spans this area despite
its lakebed name.

Without startup initialization, the player repeatedly receives 1000 `falling`
damage while standing near the switch. Source-authored Factory A teleport and
diagnostic switch starts fail in the same way. This also occurs in the authored
single-BSP `010` set. Selecting `intro_faa` through Home → Mission → Switch Zone
Set succeeds, but alone does not stop the damage. Death/reset returns to the
intro start and initial zone, explaining the observed loss of the Factory A
door after the failed teleport sequence. This observation does not accept all
streaming transitions.

Applying both exact source startup calls stopped the damage. Deathless was then
verified false, player health read 1.0, and both untouched device positions read
0. Empty serialized native `scenario kill triggers` and `NONE` reverse indices
did **not** establish runtime inactivity. No claim about the engine's internal
kill-volume registration mechanism follows from those serialized fields.

The source also scripts `camera_fa_01` and `camera_fb_01` soft ceilings. Neither
was changed to obtain the stable switch fixture. No collision mesh, BSP, shader,
sky, lighting, object physics or main scenario change was needed.

## Prepare an isolated copy

`tools/prepare_h3_player_interaction.py` copies the installed scenario into a
fresh dedicated namespace. Native XML comparisons allow only diagnostic
cutscene flags and player-start poses; they verify every existing start profile,
existing flag and unrelated section. Source anchor positions and the original
scenario hash must match. Native-load defaults that clear object-name reverse
indices or seed box-trigger sector points are restored before saving the copy,
then checked against the full original XML.

The source-selected startup calls are a console checklist in the manifest. The
helper checks each exact HSC file hash, line and named native trigger. It does
not compile or convert mission scripts. Use an initially safe intro start and
apply the calls after loading, before entering the cleanup volume.

```powershell
& 'C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe' `
  --background --factory-startup --python-exit-code 1 `
  --python 'D:\HaloRE\GitHub\Foundry-Fast\tools\prepare_h3_player_interaction.py' -- `
  --spec 'D:\HaloRE\GitHub\Foundry-Fast\tools\fixtures\h3-voi-player-interaction.json' `
  --h3-root 'D:\SteamLibrary\steamapps\common\H3EK' `
  --reach-root 'D:\SteamLibrary\steamapps\common\HREK' `
  --namespace 'levels/h3_port/040_voi/player_interaction_next' `
  --output 'D:\HaloRE\PortCensus\voi_player_interaction_next'
```

Choose unused namespace and report names. Existing reports and namespaces are
refused. `NATIVE_READBACK_VERIFIED` describes the copied authoring, not gameplay.
TagPlay must run with its working directory set to the HREK root.

## Repeatable runtime sequence

The tested `runtime_interaction_04` copy was unloaded and restored after the
manual tests. For a fresh copy prepared above, substitute its namespace and
launch from the safe intro. The session used:

```text
game_initial_zone_set intro
game_start levels\h3_port\040_voi\runtime_interaction_04\runtime_interaction_04
```

After loading, apply the source initialization before teleporting the player:

```text
(kill_volume_disable kill_all_lakebed_a)
(kill_volume_disable kill_bfg_cin_start)
switch_zone_set intro_faa
(object_teleport (list_get (players) 0) diag_switch)
```

Close the console to resume simulation. Verify player health and deathless state:

```text
(inspect cheat_deathless_player)
(inspect (object_get_health (list_get (players) 0)))
(inspect (device_get_position factory_a_entry02_switch))
(inspect (device_get_position factory_a_entry02))
```

Expected pre-use values are false, 1, 0, 0. No device setter belongs in this
test. Apply the two source startup calls again after every map reload/revert.
The one-change group requires a reset for another opening cycle; a player-driven
closing cycle has not been established by the source behavior.

Use normal movement to test the closed panels, hold E to activate the control,
then test collision during opening and walk through the open doorway. Record
these separately. Read-only endpoint queries do not prove intermediate timing
or collision. The computer-use input API in this session supports key taps but
has no hold-duration action, so the hold-E and continuous movement observations
require manual input.

The other diagnostic flags are `diag_door`, `diag_crate`,
`diag_source_factorya`, and `diag_intro`. Each flag's source or diagnostic offset
is retained in the JSON specification. `diag_crate` is near source crate 882,
paired with 881; it is not a runtime name for the unnamed crate. The copied
scenario preserves all 603 placements, all 9 BSP references and all 19 zones.

## Restore and evidence

Unload the diagnostic copy before restoring it, for example by starting the main
scenario. The main remains SHA-256
`ac7fa7442d4115c08a679050b33b520b0db6d6e6a0f4d4c440a970e2c32b7644`.

```text
game_initial_zone_set intro
game_start levels\h3_port\040_voi\full_scenario\full_scenario
```

```powershell
python 'D:\HaloRE\GitHub\Foundry-Fast\tools\prepare_h3_player_interaction.py' `
  --restore 'D:\HaloRE\PortCensus\voi_player_interaction_next\fixture-manifest.json'
```

Restore checks the exact fixture and main hashes, deletes only the recorded
scenario file, retains unfamiliar files and writes a receipt. Archived scenario
bytes and exact XML differences remain outside the editing kits.

Session evidence is under
`D:\HaloRE\PortCensus\voi_player_interaction_20260908_01`:

- `source-startup-audit.json` and `source-boundary-authoring.xml`: source HSC
  locations, original file hashes, paired trigger identities and transforms.
- `runtime-events.jsonl`: timestamps, exact commands, scenario hashes and images.
- Images 17–20: repeated damage, restored normal health, trigger membership and
  untouched closed device endpoints.
- `fixture-05/fixture-manifest.json`: the tested copy, SHA-256
  `ba84f871bb8043c69a2832494964b1882bf7d1642a6a71bb4a447668993119a9`.
- `fixture-05/restore-receipt.json`: exact diagnostic scenario removed after
  unloading; the original main hash remained unchanged.
- `harness-guards-validation.json`: stronger pose checks applied to all three
  successful copies and exact source startup calls checked against installed H3.

The five focused guard tests exercise unexpected native edits, incorrect poses,
source-script drift and guarded cleanup. They do not establish runtime collision.

The follow-up directory `D:\HaloRE\PortCensus\voi_player_interaction_20260908_02`
contains both manual observation records, captures of the original main loaded
again, and `preservation-final.json`. All 2,659 full-scenario files, 986 Factory A
files, 50 proof_box files, eight protected files and the H3 source scenario match
the startup snapshot. The diagnostic files remain archived outside the kits.

```powershell
python -m unittest discover -s tests -p test_h3_player_interaction.py -v
```
