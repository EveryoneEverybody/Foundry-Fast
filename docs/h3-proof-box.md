# H3 -> Reach native proof_box, prototype 1.9.48

This is an explicit environment compiler for H3 `levels\test\box`. It produces
new Reach authoring data and tags through the existing Foundry exporter. It does
not import a mission, AI, HSC, effects, sound, or cinematics. Normal Reach export
and H3 inspection remain independent of this command.

## Run on Nate's installed kits

From a checkout with the bundled source helpers, run:

```powershell
& 'D:\HaloRE\GitHub\Foundry-Fast\tools\Run-ProofBox.ps1'
```

The defaults are H3EK/HREK under `D:\SteamLibrary\steamapps\common`, Blender
5.2.1 under `C:\Program Files (x86)\Steam\steamapps\common\Blender`, the supplied
`H3_Reach_Box_Fixtures.zip` in Downloads, and build reports under
`D:\HaloRE\PortCensus\proof_box_build_1948`.

The standalone `Foundry-H3-proof-box-1.9.48-windows.zip` contains a complete
extension and `Run-ProofBox.ps1`. Extract it to a new directory and run that
script. It does not require installing the extension in interactive Blender.
For example:

```powershell
& 'D:\HaloRE\Deliveries\Foundry-Fast-1.9.48\runner\Run-ProofBox.ps1' `
  -H3Root 'D:\SteamLibrary\steamapps\common\H3EK' `
  -ReachRoot 'D:\SteamLibrary\steamapps\common\HREK' `
  -Blender 'C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe' `
  -Fixtures 'C:\Users\infen\Downloads\H3_Reach_Box_Fixtures.zip' `
  -WorkDir 'D:\HaloRE\PortCensus\proof_box_build_1948'
```

Use the same work directory for a later rebuild of the same target: it contains
the ownership manifest. Existing output without a matching manifest and SHA-256
is refused. `-PlanOnly` decodes and validates the source without writing Reach
data or tags. `-Lighting none` is a geometry diagnostic; final lighting defaults
to `direct_only`. Only `direct_only`, `draft`, and the explicit diagnostic skip
are accepted. The runner never edits `init.txt` or the saved Foundry project list.

## Authoring pipeline and source authenticity

1. The existing H3 scenario helper decodes the real BSP; the object helper decodes
   the real sky. One shared shader helper extracts recipes and source images.
2. Live H3 Tool XML exports supply scenario, lighting-info and sky object
   semantics. The paired ZIP is hashed and parsed as source/target evidence.
3. `environment.plan.json` retains source identities/hashes, coordinates,
   topology, material slots, transforms, collision surfaces, sky geometry,
   lighting policy, scenario scaffolding, and the selected mapping rules.
4. A fresh background Blender process constructs ordinary Foundry Reach source.
   It uses `ReachStager`, normal bitmap/shader authoring, `export_asset`, Granny,
   the existing sidecar builder/importer, `ScenarioTag`, and `LightMapper`.
5. Reach Tool owns the generated geometry, collision and lighting resources.
   ManagedBlam and Reach Tool reopen generated tags. The final playable/visual
   assessment belongs to Nate in `reach_tag_test.exe`.

No H3 runtime BSP, render, bitmap, or baked-lightmap resource is serialized into a
Reach resource. No Reach stock box BSP, collision, sky mesh or generated resource
is copied or used as a substitute. Existing native Reach shader definitions,
templates, default globals and the normal starting profile are infrastructure.
The profile's stock Reach weapons/equipment are target defaults, not ported H3
objects. A missing shared shader template is reported rather than generated over
the stock shader namespace.

The live H3 geometry used to establish this checkpoint has 1,119 render vertices
and 1,063 triangles; a separate collision mesh has 2,230 vertices and 1,078
triangles. The sky has 4,698 vertices and 1,566 triangles. Reports recalculate
these values and their bounds/hashes; they are never substituted for live decode.

## Proven mappings and explicit scaffolding

The machine-readable catalog is
`io_scene_foundry/h3_import/port_environment/mappings.json`. Every rule identifies
source/target fields, transformation, evidence and confidence.

- H3 stores the optional design reference with the BSP relationship; Reach has a
  separate top-level design block. This source has no design. A nonempty source
  design fails explicitly until its authoring adapter is implemented.
- The supplied H3 scenario has no start/profile or zone set and an unset default
  sky. Both paired scenarios have zero player starts/profiles. A deterministic
  compiler start is placed 0.2 world units above a decoded upward collision
  triangle near the XY center. A named zone activates the generated BSP; the sky
  gets an explicit activation mask and default index. No teleport script is used.
- Positions and instance/pivot transforms retain the decoder's 100 authoring
  units per world unit. Foundry uses `scale=max`, `forward=x`. Real face masks
  preserve separate render-only and collision-only structure geometry. The
  opt-in helper `--environment-semantics` verifies every collision surface ring
  against the existing ASS decoder before retaining material/flag provenance.
  The 12 material=-1 source surfaces become native Foundry `+sky0` boundaries;
  solid surfaces retain their actual source collision materials. This restores
  the source cluster's sky index without copying a compiled Reach cluster.
- All seven H3 material lighting rows have zero emission and there are no authored
  generic lights. Reach rebuilds material rows in its own surface order. The
  catalog records common emissive fields, removed H3 frustum fields and the Reach
  bounce default. Separately, the source sky render model contains 200 lighting
  samples. The first 199 diffuse samples retain direction, color and solid angle.
  The final narrow, bright sample becomes a Reach analytic sun, using radiance
  times solid angle for irradiance and the source angular size. This is an
  explicit approximation with unverified rendering parity. Nonzero emission fails rather than guessing
  a source/target material-row correspondence.
- `--single-image-pixels` is an opt-in H3 shader-helper path for the entire sole
  indexed 2D texture, even when a bitmap sequence names that image. It uses the
  existing decoder's TIFF output, including BC5 normals. Cube/volume/multiple-image
  textures remain unsupported. Ordinary inspection keeps its old preview policy.
- H3 concrete color/detail/bump images are reimported as Reach bitmaps. Source
  shader options and parameters pass through native Foundry node staging and
  shader writing. Name/type agreement does not establish rendering parity.
- The paired Reach Foundation XML uses display names for tag references. In this
  attachment the Reach scenario sky display name is `sky_daytime`; the separately
  supplied `box_sky` family is not a verified full-path link. The compiler does not
  infer a runtime reference from those labels.
- The generated sky uses its real render model with the Reach-added imposter
  policy explicitly set to `never`. Tool restores its unused imposter reference
  even after clearing it; that placeholder is retained and reported separately.
  The BSP's zero-instance imposter placeholder is also retained: the paired and
  live stock Reach box have that same missing placeholder. No missing geometry, shader,
  bitmap or other required runtime reference is allowed.

Unknown source inheritance, skinned BSPs, xrefs, negative scales, new portal
semantics, runtime material functions and nonempty authored light/design contracts
fail explicitly. Nonzero collision flags fail until mapped; this source has
only zero flags. Runtime collision/sky visibility must still be checked. No stock-sky debug
fallback is offered by this runner.

## Output and reports

All generated authoring files and tags stay under
`data\levels\h3_port\proof_box` and `tags\levels\h3_port\proof_box`.
Expected tag families are:

```text
proof_box.scenario
proof_box_bsp.scenario_structure_bsp
proof_box_bsp.scenario_structure_lighting_info
proof_box.structure_seams              (Reach Tool-generated, when produced)
proof_box_faux_lightmap.scenario_lightmap
sky\proof_box_sky\proof_box_sky.scenery
sky\proof_box_sky\proof_box_sky.model
sky\proof_box_sky\proof_box_sky.render_model
shaders\<source-name>_<identity-hash>.shader
bitmaps\<usage-specific-source-identity>.bitmap
```

Faux may create additional lightmap/resource tags in this namespace; the manifest
enumerates actual output. The generated scenario references generated BSP and
sky tags. Source H3 filesystem paths are confined to reports/provenance.

`proof_box_build_report.json` and `.md` separate planning, authoring, Tool import,
native tag readback, lighting, and runtime acceptance. The JSON includes source
hashes and bounds, mapping IDs, output paths/hashes, invocations and exit codes,
1.9.46-style timings, warnings, exact failures and unresolved limitations.
Classifications are `GENERATED`, `TARGET_DEFAULT`, `STOCK_REPLACEMENT`,
`DEBUG_FALLBACK`, or `UNRESOLVED`; this build uses the first two and records
unresolved acceptance separately. It cannot accept fallback BSP/collision/sky.

`proof_box_build_manifest.json` owns exact output hashes, target identity and
build status. Each attempt has an immutable run directory for the plan, source
extraction, command logs, worker report and validation XML. On failure, files
actually created/changed by Tool remain explicitly recorded with `FAILED` status.
Disposable wheel extraction is removed after the worker exits; useful source
extraction, authoring files and logs remain available for diagnosis.
Preexisting user content is not removed. A crash with a `BUILDING` manifest fails
closed on retry: inspect that run rather than adopting unknown files. The target
lock serializes builds independently of work directory, including Foundry's
scenario-derived Faux job directory.

The runner checks Faux logs as well as process exit codes and requires nonzero
lighting energy statistics. Local HREK exposed a shared driver defect: it invoked
phases disabled by `direct_only`, which emit `LIGHTMAPPER FAILED` while returning
zero. The existing Foundry driver now dispatches direct light only for
`direct_only`; all other preset sequences remain unchanged. `draft` is an optional
diagnostic setting and did not pass local log validation. One final-gather attempt
asserted in `faux_hive.cpp:522` (`ref.type>=0 && ref.type<k_faux_object_count`);
its logs are retained. Full runtime reference
paths come from ManagedBlam, because Foundation XML reference labels alone do
not prove identity; stock environment dependencies and missing tags are rejected.

## Tag Test acceptance

The runner writes `proof_box_init_snippet.txt` in the report directory:

```text
game_start levels\h3_port\proof_box\proof_box
```

With Tag Test closed, preserve your normal init file and append that one command
yourself, then launch `reach_tag_test.exe` from the HREK root. Alternatively, enter
the command in its console. Check that the scenario loads, a player spawns, the
H3-derived geometry and sky are visible with assigned Reach materials, and the
player can stand and walk on the world collision. Record any console/error log
and the failed criterion. No MCC cache build is part of this checkpoint.

The compiler always leaves `runtime_success=false` and `loader_status=PENDING_NATE`.
Tool/native tag checks are engineering evidence, never a playable-success claim.
Sapien, Tag Test and player/visual acceptance must be stated separately in the
delivery report. Stop after this proof; do not extend into Voi, Factory A, AI or HSC.

## Tests and package scope

Pure CI tests cover the paired XML shapes, malformed export sentinels, mapping
catalog, deterministic IR, transforms, spawn support, source hashes, pixel policy,
unsafe paths, symlink escapes and exact output ownership. Small XML authoring
excerpts and synthetic geometry are checked in; proprietary geometry/resource
fixtures are not bundled. Local fixture validation verifies all 17 ZIP members
against the supplied manifest. The Windows Blender smoke uses actual Foundry
properties and face-mask consolidation. Existing H3/Reach regression workflows
continue, and the shader-helper unit test guards the opt-in pixel policy.

CI does not pretend to run HREK or Tag Test. The prototype workflow packages a
test extension plus the standalone runner; it does not publish the normal Foundry
release/feed.
