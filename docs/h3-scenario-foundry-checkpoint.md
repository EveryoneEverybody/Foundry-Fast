# Foundry scenario source adapter — prototype 1.9.44

Use the normal **Foundry Import** command for both Reach and H3 loose scenarios.
The file browser and drag/drop dialog retain Foundry's standard scenario options
and Viewing / Reimport / Everything templates. H3 source classification occurs
before ManagedBlam startup or tag opening. A source must be inside the active
Reach tags root, configured H3 tags root, or the detected `H3EK/tags` root.
Unknown and overlapping sources fail with an explanation. The adapter never
creates an H3 project or writes H3 source tags.

For `040_voi`, enable BSP Geometry, Scenario Objects and Blender Materials, then
choose the source sky through **Sky**. In the file browser, the Sky text field's
search lists indexed source paths; drag/drop uses the existing Sky enum. None
means no sky asset or texture extraction. Advanced Scenario Inspection is inside
the same dialog. Its options default off and are outside all standard templates.
Import one H3 scenario at a time. H3 Zone Set filtering is not implemented;
use All Zone Sets.

## Blender organization and source identity

The root is `scenario_<name>`. BSP collections use Foundry's region/BSP semantic
and `COLOR_05`; Render uses permutation/BSP Category and `COLOR_04`. Original
editor folders and object categories live under the excluded `<name>_objects`
root. The selected sky is visible under a separate excluded viewing collection.
Debug content lives under excluded Scenario Inspection. Its requested category
collections use `LayerCollection.hide_viewport`, leaving the Outliner hierarchy
present and the eye control available. `LayerCollection.exclude` remains false.
This visibility state is distinct from Foundry export exclusion and survives
save/reopen. Object visibility is not individually scattered across thousands
of records.

Firing positions use one vertex mesh by default. Vertex attributes retain record,
zone, area and frame indices; `h3_point_records` names the packed JSON lookup with
every source address and resolved/source point. The full source inventory remains
queryable. Individual Empty objects require the explicit detailed option.
When objects are disabled but frame-based inspection is requested, the adapter
extracts only models identified by reference frames and their parent dependencies,
without constructing scenario object templates merely to discard them.

The real sky entry is `skies#11[0]`, referencing
`levels/solo/040_voi/sky/sky.scenery`. Live helper inspection resolved the chain
through `sky.model` to `sky.render_model`: 36,765 decoded vertices, 12,255 triangles
and 21 shader references. Sky geometry uses the existing object builder, the same
scene scale and axis transform as the BSP, and Foundry's normal sky clipping
distance convention. Source sky indices, active-BSP bits and tag chain are retained.

Normal H3 render meshes, markers, collision and skeleton construction continue to
use Foundry properties. H3 source shader and game-object paths are provenance,
never invented Reach destination references. Scenario placements and sky remain
viewing data excluded from export. BSPs are conversion candidates with native
collection/mesh organization, but their objects remain non-exportable pending
destination material and BSP-semantic validation. Standalone assets retain the
existing explicit Reference Only choice; this checkpoint does not implement an
automatic H3-to-Reach scenario conversion.

## Reuse and measured work

Each unique object source is decoded once per import; template keys retain source
variant identity. Repeated placements instance shared collections, meshes,
armature data and materials. A deque and direct maps replace repeated queue and
collection searches. BSPs, selected sky and requested objects submit one combined
shader request to the existing helper, deduplicating shader and bitmap traversal.
Blender images remain distinct when their color/data interpretation differs;
identical shader identities share preview materials and retain a source-usage
lookup rather than overwriting provenance.

Combined shader JSON is compact. Scenario loading has a separate bounded
256 MiB allowance; standalone manifests retain their 64 MiB default. The real
553-shader manifest was 73,846,974 bytes with pretty printing and approximately
40 MB compact. The first development run exceeded the old limit and used
placeholders; its 851-second result is **not** a valid material-enabled performance
comparison and is excluded from acceptance results.

Source-template bone parenting computes the same rest-parent transform directly,
avoiding a full scene dependency-graph evaluation per marker. Tests compare both
paths numerically before and after posing a rotated bone. Helper waits yield to
the next modal timer instead of spinning inside the build budget. Completed
imports release decompressed source-model and field-index copies after packing
their reports. Timings, cache counts, sky identity and parent-process working-set
metrics remain in the packed performance report. External helper memory is not
included in that measurement.

Object-helper batching, persistent extraction caching and parallel decoding are
deferred: this pass does not have an isolated process-startup benchmark that
justifies changing those protocols. The shared shader request uses the existing
helper contract. No persistent cache or worker thread touches Blender data.

## Verification and limitations

The prototype workflow gates packaging on the full pure suite in isolated
processes, existing H3 object/material/animation/reference tests, Blender 5.2.1
scenario tests, and registration/routing tests with the actual Foundry operator
on Windows. The Reach scenario/BSP backend and template functions are unchanged,
checked against normalized source ASTs from `fea63b47`. Tests cover source rejection,
option pruning, distinct variants, compact/detailed points, shared materials,
sky selection/failure, collection colors/visibility, save/reopen, late rollback
and releasing transient caches.

`tests/blender_h3_scenario_real.py` provides an opt-in fresh import through the
registered normal operator. It checks the active Reach project, source scenario
checksum, packed images and sky previews, then saves the scene and a timing report.
Use a fresh extraction directory for the requested 1,469.4-second comparison;
operating-system file-cache state is uncontrolled. A prior complete-import memory
measurement is unavailable, so report current memory rather than asserting an
unmeasured percentage reduction.

Remaining source-only features include BSP light conversion, structure design,
decals, decorators, BSP collision/portal conversion and structure merging.
Requested unsupported options are recorded and reported. Setup as Asset uses the
normal Foundry scenario asset-type setup without foreign template paths. Stored
node poses, probabilistic/inherited variants, some attachments, runtime effects,
animated shader operations and change colors retain the earlier prototype limits.
Source-grounded previews are approximations rather than Halo's renderer. Inspection
groups do not become exportable AI or gameplay data. The normal release branch,
extension feed and installed user add-on are outside this checkpoint delivery.
