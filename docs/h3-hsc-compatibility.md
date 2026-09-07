# HaloScript portability review — prototype 1.9.47

This checkpoint analyzes H3 source. It emits reports and proposed AST mapping
metadata, never converted HSC, compatibility wrappers, tags or Reach content.
The real acceptance input is H3 MCC Editing Kit `levels/solo/040_voi/040_voi.scenario`.

## Preserved baseline

The fetched `feature/h3-scenario-inspection` HEAD was
`42bd0a78c7c68362f2c8b38f9ef00c6eecc3e3e9`. Its read-only census, schema validation
and exact-float cache fix were retained. Prototype 1.9.45 was on
`fix/h3-scenario-sky-ui` at `e9810ccd70d613f4bc9f6f9a1edcaf978f449285`.
That branch was merged, preserving its RNA sky callbacks, selection validation,
sky/material acceptance checks and version-aware package verification.
Checkpoint 1.9.44's unified scenario routing, material provenance, profiling,
inspection and Reach staging remain unchanged. Normal release/feed workflows
are not modified or invoked. During validation the primary remote advanced to
`03283e4cc0e5f7ec051f3d0a030f4e64a1895e00` (source-helper profiling, prototype
1.9.46). That work was also merged and preserved, so this checkpoint is 1.9.47.

## Evidence and reviewed mappings

The primary API facts are the current [c20 H3 catalog](https://c20.reclaimers.net/h3/engine/scripting/)
and [c20 Reach catalog](https://c20.reclaimers.net/hr/engine/scripting/).
The source checkout was fetched and remains at
`6ebf90fc134255385e9d10de3d9d74a1f257ae48`. The existing facts-only signature
snapshot and its input hashes are retained. API descriptions, stock script
usage, source parameter/return types and overload forms informed the review;
none of this is labeled runtime verification.

`tools/h3_object_bridge/data/hsc_compatibility.json` is the reviewed catalog.
It contains 47 individual source-signature entries, including unencountered
overloads of reviewed functions. Each records source/target games and names,
signatures, argument and return transformations, evidence, confidence, fidelity,
conditions, and whether a proposed replacement is an engine call, wrapper,
stub, or no emitted replacement. It contains no wildcard/prefix rename rule.

| H3 function | Reach candidate | Review |
|---|---|---|
| `vs_enable_looking` | `cs_enable_looking` | Identity arguments, explicit AI retained |
| `vs_enable_moving` | `cs_enable_moving` | Identity arguments |
| `vs_enable_targeting` | `cs_enable_targeting` | Identity arguments |
| `vs_enable_pathfinding_failsafe` | `cs_enable_pathfinding_failsafe` | Identity arguments |
| `vs_go_to` | `cs_go_to` | Both explicit-AI overloads retained |
| `vs_go_to_and_face` | `cs_go_to_and_face` | Explicit AI and control boolean retained |
| `vs_play_line` | `cs_play_line` | Explicit AI, control boolean and line retained |
| `vs_custom_animation` | `cs_custom_animation` | Both explicit-AI overloads retained |
| `vs_custom_animation_loop` | `cs_custom_animation_loop` | Both nonblocking overloads retained |
| `vs_stop_custom_animation` | `cs_stop_custom_animation` | Explicit AI retained |
| `vs_abort_on_damage` | `cs_abort_on_damage` | Implicit and explicit-AI forms separately matched |
| `vs_force_combat_status` | `cs_force_combat_status` | Explicit AI retained |
| `vs_shoot` | `cs_shoot` | Both explicit-AI target forms retained |
| `vs_face_object` | `cs_face_object` | Explicit AI retained |
| `hud_breadcrumbs_using_revised_nav_points` | `chud_breadcrumbs_using_revised_nav_points` | Boolean mode query; retain branch condition |

These specific overloads have matching documented operation, return and
parameter types. Confidence is HIGH, not RUNTIME_VERIFIED. Stock Reach
`m60_ambient.hsc` also uses explicit-AI `cs_enable_looking`; implicit command
scripts are kept separate. Matching these calls does not solve actor ownership,
thread termination, animation assets, dialogue binding or multiplayer behavior.

The four H3 lifecycle functions have no reviewed safe replacement:

- `vs_reserve` assigns actors to the current script at a priority and discards
  queued command scripts. Reach `cs_run_command_script` does not establish the
  same ownership/priority behavior.
- `vs_release` detaches a specified actor from the current script.
- `vs_release_all` detaches the thread's actor set; a prefix rename or a no-op
  would discard that ownership operation.
- `vs_set_cleanup_script` registers a thread-termination callback. Appending a
  cleanup call would miss abort paths. Whole-script ownership/termination
  emulation is future research, not a verified replacement.

`vehicle_test_seat_list` maps to the reviewed `vehicle_test_seat_unit_list`
signature proposal. The boolean result and list test agree; the seat argument
changes from `string_id` to `unit_seat_mapping`. The mapping retains source
selector text, the empty all-seats selector, and a requirement to resolve the
future target vehicle's seats. Actual Voi `warthog_g`, `warthog_p`, `mongoose_d`
and empty-selector calls are retained. Stock Reach `m52_mission.hsc` uses the
unit-list API with seat selectors. No target seat binding is claimed today.

`chud_show_fire_grenades` controls the narrower H3 firebomb display. The proposed
Reach `chud_show_grenades` fallback affects every grenade indicator. This is a
PROVISIONAL, LOSSY signature/behavior proposal requiring an explicit fidelity
policy, not an exact rename. The actual Voi call uses `FALSE`.

Seven encountered breadcrumb/navpoint operations are EMULATABLE proposals.
Reach has CHUD flag/object tracking, player-specific tracking, improved
breadcrumb tracking and offsets. Future wrappers must retain the H3 team and
identifier registry, activation binding, position/object/flag, vertical offset,
deactivation lookup and recipient-player policy. A same-name state registry is
necessary because H3 deactivation can name an ID instead of its original
object. Co-op visibility, team filtering and revised/legacy presentation remain
unverified. No wrappers or stubs are produced.

`player0_set_pitch` through `player3_set_pitch` have the candidate Reach
`player_set_pitch(player, real, long)` signature. The proposed transform inserts
the corresponding Reach player literal; these are not engine globals.
`ins_scarab` performs the calls after player teleport/unhide and before placing
allies, so the reviewed impact is initial camera fidelity. Reach's
`player_control_unlock_gaze` also changes unit to player. Actual stock helper
bodies are checked structurally before its proposed helper-to-player transform
is offered. A helper merely named `player0` is insufficient evidence.

`object_get_variant_child_object_by_marker_id` remains UNKNOWN. Its description
refers to variant children/model targets. `object_at_marker`, present separately
in both games, describes attachments at markers. Equal signatures do not prove
equivalence for the scarab's `engine_inner_shield_top` target.

## Generic classifier corrections

Overload resolution uses known local/global types, user returns, nested engine
returns, literals, and typed scenario names. Equal candidates remain ambiguous.
The target comparison considers return types and parameter types for the actual
call arity; optional documentation forms do not arbitrarily win over overloads.
No global unit/player or string_id/unit_seat_mapping alias is permitted.
Numeric coercion does not establish range safety. Unknown expression types and
unverified runtime semantics remain explicit limitations of DIRECT results.

The old `sleep_until` UNKNOWN calls have three arguments: condition, polling
period and timeout. The c20 engine dump lists only the first two. A reviewed
signature supplement records `(boolean, short, long) -> boolean` for both games,
supported by Voi and stock Reach three-argument calls. For example Voi's
`intro_nav_exit` waits with `30 (* 120 30)`; Reach `m45_mission.hsc` uses
`(sleep_until (>= s_objcon_bch 10) 30 (* 30 7))`. ManagedDonkey's reconstructed
`hs_parse_sleep_until` supplies supporting type evidence (expiration is long),
not raw-native or runtime proof. Supplements are consumed by the generic
resolver; there is no special `sleep_until` classification branch.

The scenario's compiled script/global declaration table supplements physical
source declarations. `040lb_cov_flee`, `040lb_cov_flee_cleanup` and
`040pb_scarab_intro` resolve there, while their generated bodies stay unavailable.
Excluded physical files are not activated. Script references passed to `wake`,
command-script APIs and cleanup callbacks become static script-dependency edges.
Overlapping unquoted script/scenario names use the expected typed namespace;
local/global variables retain scope. Unproven namespace alternatives remain
unresolved type evidence; call-position collisions produce diagnostics.

## Context and missing-reference relevance

`hsc_context_reviews.json` records 74 real-source reviews, pinned to the complete
source file's SHA-256, enclosing script and explicit function list. Changed
contents invalidate a review. Unreviewed calls are UNKNOWN; no function-name
heuristic assigns mission blockers. The report retains API evidence/confidence
separately from context evidence/confidence and exact call locations/ASTs.

The campaign completion predicates and skull award calls belong to the dormant
`gs_create_primary_skull` / `gs_award_primary_skull` flow. They manage the optional
Catch skull, and their seven calls are OPTIONAL. The six remaining conservative
script mission blockers are `vs_reserve` and `vs_release_all` in
`vig_cor_mar_open_up`, plus `vs_release_all` in `button_pusher01`,
`button_pusher02`, `button_pusher03` and `fab_button_pusher`. Those authored paths
combine actor lifecycle with door power/position changes. This does not prove
that no player-operated alternative exists.

Missing references now carry their own planning relevance and severity.
Membership in the provisional boot/combat closure is distinguished from
geometry needed for loading and from visual resources. A cinematic-only label
requires every observed path to cross a cinematic container. Unknown runtime
necessity remains UNKNOWN; optional/unreached and progression reachability are
not invented. No aggregate boot-critical flag is copied onto every missing tag.

Factory A / `tank_room_a_covies` remains the selected MINIMUM_COMBAT_SET
candidate with 116 additional assets. Selection checks `factory_a_start` and
the expected authored squads, retains all other clusters, and follows static
call/wake/command/cleanup dependencies. It does not implement the encounter.

## Real-script validation results

| Classification | Old raw unique | Reviewed unique | Reviewed call sites |
|---|---:|---:|---:|
| DIRECT | 235 | 235 | 6,509 |
| RENAMED | 0 | 15 | 214 |
| SIGNATURE_CHANGE | 1 | 7 | 46 |
| EMULATABLE | 0 | 7 | 33 |
| STUB_CANDIDATE | 0 | 0 | 0 |
| UNSUPPORTED | 37 | 8 | 92 |
| UNKNOWN | See note | 1 | 1 |

There are 273 documented engine functions and 6,895 engine calls. The old report
also counted five unknown names/shapes alongside those categories, including
`sleep_until`; it was not an exclusive partition. The new unresolved-name
inventory contains one additional source call, `cs_go_to2` at
`040_voi_mission.hsc:2265`, outside the engine-function totals. It is not silently
renamed to `cs_go_to`.

The full graph remains 36,806 tags, 537 direct dependencies, 36,268 transitive
dependencies, 1,382 missing references, 108 groups and 88,088 edges. The updated
script pass discovers 13 files, analyzes the same 7, reports 1,740 scenario
symbol references (20 additional references recovered from typed namespace
collisions), zero unresolved typed symbols and zero parser/declaration errors.
See the delivery validation record for the exact final commit, CI and report
hashes. Use the [Windows census command](h3-port-census.md#windows-command) to
regenerate JSON, Markdown and the standalone transpiler mapping table.
