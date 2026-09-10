# Manual H3-port lighting preparation and Reach Faux

`tools/Bake-H3Port.ps1` runs locally and needs no connected assistant. It uses
Python 3.11+, background Blender compatible with Foundry's bundled wheels, and
an installed HREK. It does not install or patch engine binaries.

The generic light translator converts source/world attenuation distances to
Reach authoring units exactly once (Ã—100). Source plans, positions, intensity,
color, cones and orientation remain unchanged. Surface emitters use a separate
source-controlled conversion: explicit H3 ranges ×100; disabled H3 attenuation
uses its finite 20/21 world-unit surface default, authored as 2000/2100 in Reach.
Stored disabled distances remain in source provenance and are not active ranges.
Normal native lighting validation and the read-only audit use the same units.

## Configuration

Keep machine paths, accepted plans and experimental presets outside this repo.
For example, save a local JSON config:

```json
{
  "HrekRoot": "C:/Games/HREK",
  "Blender": "C:/Apps/Blender/blender.exe",
  "Scenario": "levels/h3_port/sample/sample",
  "Plan": "C:/Work/accepted/environment.plan.json",
  "RunRoot": "C:/Bakes",
  "Bsp": ["0000"],
  "Quality": "low",
  "Workers": 4,
  "LightGroup": "",
  "Mode": "ValidateOnly",
  "Name": "range-check",
  "OutputPolicy": "GuardedInPlace",
  "IntervalSeconds": 30
}
```

```powershell
.\tools\Bake-H3Port.ps1 -Config C:\Work\lighting.json -ValidateOnly
```

Explicit command arguments override the config. `-Preset NAME -PresetDirectory
DIRECTORY` loads `DIRECTORY/NAME.json`. Never save `ConfirmInPlace` in a preset:
the PowerShell entry point requires this switch on the actual invocation.

`Bsp` accepts scenario indices (`0000`), exact short BSP names, a comma-separated
list, a PowerShell string array, or `all`. Indices are target **scenario** indices,
not source BSP numbers. A list executes separate complete jobs sequentially;
`all` executes one combined job. Their photon budgets/transport need not match.

Workers is an integer1â€“64 (operator guard, not an engine limit), default1.
There is no Auto setting. It controls concurrent farm clients: indices0â€¦Nâˆ’1
each receive countN, followed by one merge with N after every client succeeds.
It does not cap the internal threads of Tool/VMF. Choose based on available RAM
as well as CPU; each process has its own allocations.

## Prepare without Faux

```powershell
# New disposable lighting-tag copies; not a runnable/isolated scenario.
.\tools\Bake-H3Port.ps1 -Config C:\Work\lighting.json -PrepareOnly `
  -OutputNamespace levels/h3_port/sample_prepare_001

# Explicitly update installed lighting inputs, with verified backups, no Faux.
.\tools\Bake-H3Port.ps1 -Config C:\Work\lighting.json -PrepareOnly `
  -OutputPolicy GuardedInPlace -ConfirmInPlace
```

Prepare requires an accepted plan with a valid embedded hash, no blocking
contracts, and matching native scenario/BSP/light relationships. It uses the
real H3 translator and Reach writer's attenuation-only path. Only the four
generic definition attenuation bounds are written. Instances, material rows
and all other native fields must compare equal after reopening the tag.
Plan source data remains immutable. Running again derives values from that
source plan, never from already-scaled native values.

Reports distinguish `SOURCE_WORLD_UNITS`, `REACH_AUTHORING_UNITS` and
`EXPECTED_FAUX_WORLD_UNITS` (native load-postprocessed units). ValidateOnly
reports `needs_preparation` if the installed inputs still have old ranges;
this is a successful validation of a proposed preparation, not a claim that
the installed bounds are corrected. BakeOnly with a plan refuses uncorrected
inputs. ValidateOnly may omit a plan for native stage/output preflight alone.
PrepareOnly and ValidateOnly have no Tool launch path, and their native worker
rejects subprocess/Tool calls.

## Manual baking and stages

Close Tag Test, Tag Play and kit editors/Tool clients first. The guarded path
refuses conflicting clients; it never kills someone else's process.

```powershell
.\tools\Bake-H3Port.ps1 -Config C:\Work\lighting.json -PrepareAndBake `
  -OutputPolicy GuardedInPlace -ConfirmInPlace
# Or retain already-prepared inputs:
.\tools\Bake-H3Port.ps1 -Config C:\Work\lighting.json -BakeOnly `
  -OutputPolicy GuardedInPlace -ConfirmInPlace
```

Supported presets are checked against the installed lightmapper globals:

| Quality | Farm phases, each followed by its merge |
|---|---|
| direct_only | dillum |
| draft | dillum, radest_extillum, fgather |
| low, medium, high, super_slow | dillum, pcast, radest_extillum, fgather |

Every job starts with `faux_data_sync`, `faux_farm_begin`, then the phases above,
then `faux_farm_finish`, `faux-reorganize-mesh-for-analytical-lights` and
`faux-build-vmf-textures-from-quadratic`. Disabled phases and their merges are
omitted. Changed preset phase flags or missing executable commands fail closed.
`LightGroup` is passed as its own argument, including an actual empty string.

Every invocation creates a new timestamp/random run directory. Every job gets
a new positive signed32-bit ID, checked for collisions again before begin.
Existing/partial blob directories are never reused. The kit lock excludes other
instances of this runner, including restoration.

## Monitoring and reports

Keep the local console open. Every interval it prints stage/total elapsed time,
owned active client count, configured workers, PIDs, available aggregate CPU
seconds/RAM, log location and the last available log line. Buffered logs are not
a reliable heartbeat, and an idle sample is not automatically treated as failure.
Each client completion is printed. `status.json` is atomically replaced and
`telemetry.jsonl` preserves samples. An optional second-console monitor is:

```powershell
.\tools\Monitor-H3Bake.ps1 -RunDirectory C:\Bakes\THE-RUN
```

A nonzero exit, fatal log marker or missing success marker stops the sequence
and terminates only the remaining clients launched in that group. The failure
includes the stage, exit code, exact command and log. No later merge starts.

Each run retains config, commands, stage plan, before/after hashes, logs,
verified backups, native operation receipts, status and result. Successful
bakes copy solver data into the run; failed partial jobs remain at the recorded
kit `faux/<ID>` paths. Result includes commit/dirty state, scenario/BSPs,
quality/worker settings, timestamps/durations, every client exit, warnings,
changed files, native lightmap references/hashes and preservation status.
Warnings remain visible even if not fatal. `PASS` means pipeline/native checks;
visual acceptance remains **RUNTIME_TEST_PENDING**.

An optional local config `"SolverProbe":{"Bsp":0,"Definition":0,"Instance":0}`
requires a plan and a selected spot light. The post-bake check rejects missing
or ambiguous matching records and the old hundredth-scale effective far range.
It checks solver parameters, not pixel visibility. The MAX constructor's
near-end handling can differ from native postprocessed near bounds; both are
reported. No fixture-specific indices are hardcoded in the runner.

## Output policy and recovery

Shared-geometry isolated diagnostic output has **not** been certified. Merely
cloning a scenario is insufficient ownership isolation for BSP-derived lighting
inputs and mesh reorganization. The runner rejects shared/outside-namespace
BSP/lightmap dependencies and nonstandard/local lighting references. Disposable
prepare copies must not be mistaken for an isolated bake setup.

The supported fallback is explicit GuardedInPlace. It verifies and backs up
every existing file in the dedicated scenario namespace before mutation,
including shared scenario-level lightmap/probestore state. The current pre-run
installation is the baseline; if it is already experimental, the backup is too.
Completed results remain installed for manual testing. No automatic restore
occurs on success or failure. Unexpected changes outside the allowed output
set fail the report and are preserved for inspection.

To explicitly reject a result, close kit clients and run the generated
`Restore-Bake.ps1`. It requires an exact candidate after-hash inventory and
verified backups before any write. Concurrent changed/new/missing files refuse
restoration. It restores original bytes and removes only new files named in the
captured after inventory. It does not recursively delete the namespace. A
separate restore receipt leaves the completed run evidence unchanged.

**Resume is not supported.** Ctrl+C stops owned clients and attempts final
hashes/reporting. After a reboot/forced kill, a stale kit lock or absent after
snapshot requires manual process/file review; neither resume nor blind restore
is attempted. Keep the partial run/job. Do not simply delete its blob and reuse
the ID. After validating/restoring the intended starting state and explicitly
removing a proven stale lock, begin a new run at data_sync/begin and repeat all
enabled phases. Missing after hashes cannot be reconstructed as trusted
concurrency evidence automatically.

The successful run also writes `tag-test.txt`. Set optional `InitialZoneSet` in
local config for a scenario-specific console sequence. Launching/viewing the
game is manual; the helper makes no runtime acceptance claim.


## Surface-light preparation

PrepareOnly also resolves positive source material rows through the existing BSP
shader and imported-material references. It verifies power, color, focus, quality,
flags and bounce before changing only falloff/cutoff, then reopens the native tag.
Reports include old/new values, SOURCE_H3_SEMANTICS, REACH_AUTHORING_VALUES and
EXPECTED_FAUX_EFFECTIVE_VALUES. Source plans remain immutable. Ordinary Reach
material authoring and runtime shader self illumination are unchanged.

Unsupported frustum/flag contracts and explicit non-increasing ranges fail closed.
The expected effective cutoff includes the shared 0.001 minimum range separation.
Use a fresh OutputNamespace for disposable lighting-input proof; this is not an
isolated bake namespace. PrepareAndBake applies the correction only after the
existing explicit guarded-in-place confirmation. No bake runs in PrepareOnly.
