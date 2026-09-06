# 040_voi scenario inspection, prototype 1.9.41

The real 1.9.40 report retained 2,705,207 fields, 683 references and 11 blobs.
All nine BSP entries had status `error`, with `Missing source dependency` and
Windows error 3. The log's `Decoding BSP` messages marked attempts, not success.
The manifest source was `tags/levels/solo/040_voi/040_voi.scenario`, demonstrating
that the supplied dependency root was above the actual tags directory.

Running the same installed helper with `H3EK/tags` as its root successfully
extracted all nine BSPs: 1,308 definitions and 6,884 placements. The shader helper
then extracted 195 shaders and 429 bitmap bindings. These are extraction counts,
not proof of complete original authoring data or faithful material rendering.

The source-root resolver now accepts a kit directory when its direct `tags`
child contains the selected source. Both the source-relative identity and all
dependency helper commands use that normalized root. Custom roots remain
supported, and the normalized root is still checked against active Reach tags.
Per-BSP failures are printed by the helper and summarized in Blender Output.

## Coordinate evidence

The importer pins blam-tags `5d0509fb75eadb96ac7774542ca0b2c10aed7b00`.
Its `blam-tags/src/geometry.rs` defines `SCALE = 100.0`; the H3 JMS vertex
readers in `jms.rs` and the BSP geometry/placement paths in `ass.rs` multiply
positions by that constant. Foundry's working H3 `BuildSession.position`
then applies `import_transform.scale_factor` and the forward-axis rotation.
The scene factor is 0.03048 in Blender scale mode and 1 in Max scale mode.

Scenario inventory points are raw source-world coordinates. They require the
100 multiplier exactly once, followed by the same scene factor and rotation.
The existing scenario implementation already performed that conversion.
It now calls the shared Foundry position function and records the display
settings explicitly. No new character-height assumption or corrective global
scale has been introduced. Missing BSP context alone does not prove a scale bug;
objects imported under different scene scale settings can still differ.

`blender_h3_scenario_units_smoke.py` compares the actual BSP mesh and every
authored point/curve category with the working object transform in both scene
scale modes and both tested forward axes. It also checks that the original
inventory and packed source metadata retain their unmodified coordinates.

## Progress ownership

Both Asset and Animation commands emit explicit parent-import status messages.
The Output viewer stays active through helper completion, validation, retention
and construction, until the parent reports completed, cancelled or failed.
Changed log messages are throttled to one per second; header updates continue
independently. Validation reports actual fields processed, retention reports
chunks retained/total, and no spinner frames are added to the detailed log.

The full real-data construction check also exposed slow Blender Text insertion:
the first BSP's source JSON alone is about 67 MB. Source JSON now uses whitespace
line breaks, and retained base64 wraps at 76 columns. Source values and binary
checksums are unchanged; the archive reader accepts both old and wrapped text.

The normal release branch and extension feed are outside this prototype change.
The packaging job depends on successful Windows helper and Blender CI jobs.
