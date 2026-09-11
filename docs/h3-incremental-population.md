# Incremental native scenario population

`tools/run_h3_scenario_objects.py --populate-existing` reconciles scenery,
crates, machines and controls into an existing scenario. The ordinary fresh
build/integration path retains its replacement behavior.

Required inputs are `--plan`, `--integrate-inventory`,
`--population-root-receipts`, the existing kit/Blender/work-directory arguments,
and the runner's device-animation inventory argument. Add
`--population-dry-run` to inspect the complete diff. Use
`--population-family` repeatedly to select a subset. After application, pass
the emitted `placement-provenance.json` with `--population-provenance` when
running again. An optional `--population-protected-manifest` accepts a list
of `{path, sha256}` records; the scenario itself is checked structurally and
against the current operation's backup.

The planner preserves existing rows and uses explicit palette, name, parent
and device-group maps. A preexisting placement is adopted only when its unique
source ID, root and complete authored-field comparison agree. Conflicting names,
groups, source IDs and changed owned outputs are deferred without deletion or
renaming. Parent deferrals propagate independently of unrelated roots.

Root receipts use `object_receipts.root_identity` and `reusable_root` instead
of a global batch-plan hash. They contain source/dependency hashes, an authoring
rule fingerprint, a semantic closure fingerprint, destination identity, native
readback and hashes for the native dependency outputs. Minting a receipt requires
verified source/decoded provenance and native readback; hashing arbitrary files
does not establish semantic correctness. `native_object_closure.read` reads the
supported native roles without following inactive shader-definition options.
Existing accepted material outputs can remain dependencies without rewriting
them. A source or rule revision invalidates the affected root receipt.

Older compiled physics labels can be verified using the exact compiled source
receipt and unchanged physics-output hashes. This compatibility readback retains
source body/list/primitive/region/permutation/material checks. Label collisions
without explicit provenance remain blockers. New authoring always uses the
current source-index labels.

Application appends only the selected palettes/placements and required
names/groups/designer-zone memberships. It verifies the installed BSP index
contract, saves once if necessary, reopens, verifies authored fields and exports
Tool XML. Protected scenario sections and preexisting rows are compared with the
baseline. A no-op skips `Save()` and requires the scenario byte hash to remain
unchanged. It never rebuilds BSPs or lighting. Native validation is reported
separately from `runtime_status = NOT_TESTED`.

`asset_closure` and `scenario_census` provide deduplicated semantic relationships,
regular-family accounting and streaming specialized-system counts. Unsupported
leaves remain explicit; deferred-family metadata coverage must not be presented
as a fully decoded closure. Detailed integration evidence belongs outside the
implementation repository.
