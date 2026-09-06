# H3 scenario content prototype (1.9.42)

Real 040_voi feedback confirms spatial alignment. This change preserves the established coordinate conversion.

## Ground material diagnosis

The real extracted BSP references identify `natural/lakebed.shader_terrain`,
`natural/lakebed_b.shader_terrain`, and `concrete/asphalt_c_wet_puddle.shader_terrain`
under `levels/solo/040_voi/shaders/`. Their descriptions resolve as `rmtr`, and the
referenced bitmaps were extracted. The previous generic object preview ignored
`blend_map` and `base_map_m_N`, producing a misleading successful plain preview.

Terrain previews now connect active layers using normalized linear blend-map
channels, base/detail textures, and the dynamic-morph transition where selected.
The equations come from `hlsl/terrain.fx`, `sample_blend_normalized` and
`ACCUMULATE_MATERIAL_ALBEDO`, in
[Halo3-Shader-Source](https://github.com/halohlsl/Halo3-Shader-Source/tree/257ca5f9e1149a31dbfb6a7c9141bd232f590e5b).
Lighting, specular/wet reflections and detailed normal blending remain approximate.

The inspected `grey100` shader is a constant-color object shader, not a missing
bitmap. Its decoded color is retained in nodes and the solid material color;
scenario construction no longer overwrites that color after preview creation.

Each BSP material retains its exact shader identity, slot, source triangle use
count, preview result and stage-specific issues. Foundry Output prints unresolved
references/descriptions/bitmaps/classes and construction failures. The packed
`H3 BSP material report` remains available after extraction files disappear.
No destination shader paths are generated.

## Source content and organization

Scenery, machines, controls, crates, vehicles, weapons, equipment, bipeds, giants,
effect scenery, sound scenery, light volumes and terminals resolve through their
source palettes. Unique tags use the existing object extraction helper. Blender
templates use the existing `BuildSession`, cached by source tag and variant, and
placements instance those collections. Named instances retain source transforms,
palette/name indices, variants, editor folders, parent references and state fields.
Templates and instances are excluded from Foundry export.

Explicit deterministic variant permutations are selected when present in decoded
geometry. Probabilistic/inherited variants, stored node poses, damage states and
child attachments remain documented rather than simulated. Unresolved object
sources become position markers; unresolved parent-relative placements remain in
the report without invented world coordinates. Non-geometric sound/effect/light
records may therefore remain markers with source metadata.

World trigger boxes, player starts, cutscene flags/orientation points, squad starts
and area means are visualized. Source squad groups, squads, fire teams, zones,
areas, objectives/tasks and designer zones become named collections containing
their readable references. Firing positions and script points join their source
area and point-set collections. Giant sectors and rails retain their established
display. Camera points do not invent lens settings. Area means are points, not
invented volume boundaries. No runtime AI execution relationship is claimed.

The inventory remains the authoritative retained record, including ambiguous and
undecoded data. Typed Euler components now retain raw source order and float bits;
old rounded decoder-debug angles are not silently parsed as exact transforms.

## Validation and delivery

Focused pure tests cover palette reuse, names, transforms, variants, source identity,
groups and material failure stages. Blender tests exercise the actual existing
object builder, shared collections, distinct variants, folder organization, export
exclusion, cancellation and persistence. A numerical Cycles test measures morph
and dynamic-morph terrain albedo and checks constant grey and missing bitmap reports.
The prototype workflow retains existing object/material/animation coverage and
packages only after its Windows helper and Blender test jobs pass. It publishes
only a test artifact, without updating the normal release branch or remote feed.
