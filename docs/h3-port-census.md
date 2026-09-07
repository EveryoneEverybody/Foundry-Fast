# H3 portability census prototype 1.9.47, schema v1

`h3-scenario-inspect port-census` analyzes a loose H3 MCC editing-kit scenario
and its reachable tags without Blender. It generates a proposed Reach build
plan. It does not generate, convert, rewrite or compile game content.

The acceptance target is `levels/solo/040_voi/040_voi.scenario`. This checkpoint
does not target 070_waste. Observed shared dependencies may lead to references
owned by other missions; those remain labeled as transitive evidence.
Foundry's active Reach/Omaha project is not changed.

## Windows command

Extract the standalone `H3-port-census-1.9.47-windows.zip` into, for example,
`D:\HaloRE\PortCensus\helper`. In PowerShell:

```powershell
& 'D:\HaloRE\PortCensus\helper\h3-scenario-inspect.exe' port-census `
  'levels\solo\040_voi\040_voi.scenario' `
  --h3-tags 'D:\SteamLibrary\steamapps\common\H3EK\tags' `
  --reach-tags 'D:\SteamLibrary\steamapps\common\HREK\tags' `
  --h3-data 'D:\SteamLibrary\steamapps\common\H3EK\data' `
  --definitions 'D:\HaloRE\GitHub\Foundry-Fast\.cache\reference-definitions' `
  --output 'D:\HaloRE\PortCensus\040_voi-report'
```

Change the definitions path to your local definitions checkout if needed.
It must contain `halo3_mcc` and `haloreach_mcc`, with inherited group JSON files
beside their children. The implementation study used definitions revision
`0b21715e93110a28aaf53bc7122bba5d96b496aa`. Definitions are optional: without
them the tool still reports dependencies, policies, scripts and planning sets,
but structural compatibility is explicitly unavailable. A custom definitions
root can provide additional H3/Reach schema data; all profile JSON hashes are
recorded, including inherited definitions.

The output folder is created automatically. Choose a new folder for each report;
existing reports are never overwritten. The files are:

- `040_voi_portability_report.json` — machine-readable engineering report.
- `040_voi_portability_report.md` — engineering summary.
- `040_voi_hsc_transpiler_mappings.json` — reviewed mapping catalog and call AST plans; no source emitted.
- `040_voi_dependency_graph.json` — dependency nodes and evidence-bearing edges.
- `040_voi_timings.json` — measured phase times and cache hits.
- `cache/` — disposable, source-scoped scan cache, unless `--cache` is supplied.

Both tags roots and the scenario are required. The scenario can be an absolute
path or relative to `--h3-tags`. `--scripts <directory>` overrides mission source
discovery. `--h3-data` also discovers shared `data/globals/*.hsc` sources. When
the embedded scenario source-file table is available, ordinary discovery uses
its names to select sources for function analysis. Other discovered files still
retain their ASTs and an excluded-source label. Explicit `--scripts` analyzes
the supplied sources, even when they differ from the compiled source table.

`--hsc-catalogue <json>` accepts the versioned `foundry.hsc-signatures` v1
format used by the bundled catalogue. `--baboon-reference` and
`--troop-reference` record explicit local reference revisions. Otherwise the
implementation-study pins are recorded and identified as such. The census
does not fetch external websites or alter any reference checkout.

`--all-fields` walks large resource tags as well as their dependency streams.
The normal scan uses `want` for tags over 4 MiB when that stream exists, with an
explicit unobserved-field diagnostic. This avoids decoding large resource data
just to discover declared references. There is a 512 MiB per-file read limit,
a ten-million-field per-tag limit, and a 100,000-node graph limit. Read failures
retain their exact errors and any dependencies already recovered. Exceeding the
graph limit fails rather than silently reporting a complete truncated graph.

## Safety and determinism

All game content is opened for reading. Output and cache paths are resolved
against their existing ancestors before any directory creation. The entire
normal kit parent is protected when the supplied root is named `tags`, including
data, project configuration and settings. Explicit data, scripts, definitions
and reference directories are also protected. Junctions/symlinks in the source
indexes are skipped and diagnosed. Output inside a kit, output containing an
input root, and output routed through a junction into a kit are rejected.

Only report/cache files are written. There are no calls to tag writers,
ManagedBlam, Tool, cache building, Sapien, Blender, audio extraction or release
publishing in the census command. Test code creates synthetic fixture tags in
its test-output directory; it does not use installed game tags as write targets.

Canonical identities include the source game, canonical tags root, normalized
case-insensitive relative path and group. Graph traversal has cycle protection,
stable breadth-first discovery and sorted outputs. Cache identity includes the
source root, decoder, schema contents, file size/mtime and scan mode. Reusing a
cache never imports a graph from another source root. Metadata-preserving file
edits are outside the size/mtime invalidation contract; use a fresh cache after
such edits. Timing values live outside the deterministic engineering reports.

## Evidence and report contract

Schema: `foundry.h3-reach-portability-census`, version `1`.
The JSON Schema is `tools/h3_object_bridge/data/port_census.schema.json`.

The dependency graph is the union of actual parsed tag-reference fields and
declared `want` streams. It does not assume either source is complete or that
every edge is runtime-required. Disagreements retain both sets. Missing source
files remain graph nodes. Direct/reverse references, shortest observed depth,
first discovery chain and local/shared classification are retained per tag.

`schema_compatibility_profiles` contains H3/Reach definition comparisons.
`serialized_layout_comparisons` compares each observed distinct serialized H3
layout with a Reach definition profile. Per-tag records point to the latter
when available; resource tags whose main layout was not read retain the explicit
definition-only fallback. Layout identities fingerprint nested field names,
types, widths, options, containers and opaque definitions, not just root GUIDs.
Potential field losses are counted once per interned struct pair, not once per
runtime instance. Identical fields, aliases, defaults, dropped fields, option
losses/remaps, conversions and blocked/opaque fields remain available in JSON.

These are distinct:

1. Serialized/schema observations.
2. Semantic interpretation and proposed port strategy.
3. Official Reach loader/build acceptance.
4. Live Reach behavior.

No report equates a schema match with engine portability. Target acceptance
remains `NOT_TESTED`. Initial policy assigns `TRANSLATE`, `TRANSLATE_FIXUP`,
`REBUILD`, `REPLACE`, `STUB`, `DROP` or `MANUAL`; proposed strategies are
provisional. Unknown groups are not silently treated as convertible.

Exact same-path and same-stem/different-group Reach collisions are reported.
Existing Reach files are candidates, not proven stock assets or equivalent
behavior. No candidate is silently selected. Mission-local proposed rebuild
paths use `levels/h3/<mission>/`; shared content uses `h3_port/`. A reviewed stock
replacement would remain at its existing Reach path.

## Reused Foundry work and external references

The existing inspector and census share `source_walk.rs` and `source_values.rs`.
The census uses the existing pinned `TagFile` reader and its dependency/header
APIs. It does not parse the scenario binary independently or use Blender as its
database. Existing material descriptions are called directly without bitmap
extraction or shader writes. Object, scenario, animation, attachment and material
capability statements cite the existing code and tests.

Studied revisions:

- [Foundry-Fast scenario branch](https://github.com/EveryoneEverybody/Foundry-Fast/tree/feature/h3-scenario-inspection), starting at `3a18bb38791cf9b713581d525582dfa134889184` (prototype 1.9.44).
- [Baboon](https://github.com/Zoephie/Baboon/tree/f4df490579f83697aa7d56ade53abf8071ff5449), including import/conversion workers and compatibility generator.
- [blam-tags](https://github.com/Zoephie/blam-tags/tree/5d0509fb75eadb96ac7774542ca0b2c10aed7b00), Foundry's pre-existing dependency pin.
- [Definitions](https://github.com/camden-smallwood/definitions/tree/0b21715e93110a28aaf53bc7122bba5d96b496aa), also Baboon's pinned definitions.
- [Troop Baboon research](https://github.com/EveryoneEverybody/Troop/tree/69c574d238315c05e0f49140509d9548e20fcc0e/Analysis/Baboon), preserving its source/semantic/loader/runtime distinction.
- [c20 H3](https://c20.reclaimers.net/h3/engine/scripting/) and [Reach](https://c20.reclaimers.net/hr/engine/scripting/) scripting references, with the offline signature facts generated from c20 commit `6ebf90fc134255385e9d10de3d9d74a1f257ae48`.

No Baboon or blam-tags implementation source was copied, vendored or transplanted.
Neither inspected repository presents a clear top-level license grant. This
change retains Foundry's existing pinned dependency and calls its public
read/comparison APIs; it does not claim to resolve the pre-existing dependency's
licensing. Baboon's source-scoped identities, independent compatibility/policy
layers, loss reporting, and native/generated-layout distinctions were reused
conceptually. The referenced `mappings/conversion_mappings.json` is absent in the
inspected Baboon checkout: no unavailable reviewed mapping is inferred or applied.
c20's GPL-3.0 facts-only catalogue generation is reproducible with
`tools/h3_object_bridge/tools/build_hsc_catalogue.py` and records input hashes.

## Known limits

- No actual conversion, destination tag creation, script rewriting, FSB build,
  shader-tag generation, BSP export, lightmapping or playable mission generation.
- Full references, counts and schema losses are retained. Optional non-scenario
  metadata summaries are bounded to 256 rows per tag and diagnosed when bounded;
  they are not a full replacement for an audio/resource extractor.
- Decorator instance coordinates and navigation point coordinates are omitted;
  their block totals and references remain available. Scenario entity scalar
  values appear once under address-keyed fields, with container/resource records
  retained separately. Category counts prefer the root block when present;
  `block_counts` contains totals across every same-named nested block.
- The source-file table distinguishes physical, missing and engine-generated
  HSC. Generated cinematic/Cortana source is not decompiled. Classification
  counts now assign each engine name one conservative bucket, with per-call and raw-name totals separately retained. Unresolved source names are separate from documented engine functions.
- Source fields establish authored names and relationships, not runtime
  activation, active zones, attachment transforms or designer intent.
- Minimum boot assets are a filtered closure around one authored BSP candidate
  and the scenario sky, plus target-side requirements. Other BSP candidates remain
  visible. No loader-validated minimum is claimed.
- Combat candidates come from actual squad groups and palette joins. The reviewed Factory A / tank room candidate is preserved with its authored script dependencies; no runtime access is claimed.
- HSC has a real nested parser with comments, strings, declarations, parameter
  scopes and line/column/byte locations. Malformed forms are diagnostics.
  `DIRECT` compares the resolved overload and active target signature using partial type inference. It does not establish range safety or semantic equivalence. See the [reviewed compatibility catalog](h3-hsc-compatibility.md) for explicit renames, transforms, wrapper proposals and context reviews. Unknown overloads and missing source names remain explicit. No blanket prefix substitution or automatic stub is applied.
- Ordinary `.shader` source snapshots can be eligible for current Reach node
  staging; target sockets, pixel support and final shader-tag parity are separate.
  Terrain preview does not imply ordinary Reach node staging.
- Stored-pose decoding remains unsupported. No short-quaternion codec is invented.
- Engine implicit dependencies, dynamic script-created paths and external-bank
  metadata may extend the observed graph. `want` can also include build-only or
  transitive entries. The report is a factual observed graph with explicit limits.

## HaloScript compatibility checkpoint

Prototype 1.9.47 adds a deterministic reviewed mapping catalog, raw versus effective totals, exact source expressions, compiled scenario script declarations, overload resolution and content-pinned context reviews. The machine-readable transpiler table is a separate output and is also embedded in the report. Missing-reference severity is per relevance group. See [evidence and real 040_voi results](h3-hsc-compatibility.md).

## Validation and delivery

The standalone prototype workflow tests the helper on Windows and Linux and
uploads `H3-port-census-1.9.47-windows.zip` with a SHA-256 file and build commit.
The existing scenario prototype workflow still provides Blender regression
coverage. Neither workflow deploys the normal Foundry release/feed for this branch.
No Foundry addon installation is required to use the census.

```powershell
cargo test --release --manifest-path tools/h3_object_bridge/Cargo.toml
cargo build --release --manifest-path tools/h3_object_bridge/Cargo.toml --bin h3-scenario-inspect
python tools/h3_object_bridge/tools/validate_port_census.py 'D:\HaloRE\PortCensus\040_voi-report\040_voi_portability_report.json'
```

Tests cover source identity, cycle/dedup/missing-reference handling, group counts,
path mapping, destination collisions, structural losses, strategies, HSC ASTs,
source locations, user versus engine calls, typed scenario references, unsupported
calls, minimum sets, blockers, report schema, repeat determinism, cache reuse and
protected output rejection. Real-kit validation is recorded separately from these
synthetic tests and does not establish Reach runtime behavior.
