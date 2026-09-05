# H3 material provenance

Foundry Fast 1.9.27 extends the 1.9.26 shader preview pass with a source description for each shader. Existing bitmap extraction and Blender preview nodes remain separate from this description. No Reach tags are generated.

## Data

`shader_manifest.json` retains `foundry.h3-shaders` version 1. Each shader may now contain `source_description`, format `foundry.h3-material`, version 1. Older manifests without descriptions remain supported.

The description retains source identity and class, the render-method definition, category and option names plus source indices, parameter declarations and defaults, authored fields, sampler settings, bitmap references, RGBA values, packed source colors, and texture-transform samples. Animation functions retain their raw bytes and input names. Renderer-provided externs are not presented as artist bitmaps.

Raw field maps only include fields that the reader exposes as present. Real-value bit patterns retain non-finite source values without inventing usable resolved values. Declarations and overrides remain separate. A source parameter record does not imply that every field overrides its default: bitmap sampler flags still govern the merge.

`description_status` is independent of preview status. It can be `resolved`, `partial`, `failed`, or `unsupported`. `conversion_status` is always `source_only`, and `destination_shader` is null. Matching Reach option names in the existing candidate table does not change either field.

Global option declarations are retained but not merged by the pinned resolver. Existing postprocess constants and bindings are retained but not applied to authored parameters. Animated values and transforms are decoder samples at zero, not converted animation. Reference inheritance remains unflattened. Resolved descriptions initially cover ordinary `rmsh` object shaders; other families retain raw fields with unsupported diagnostics.

The shader helper reuses its option-tag cache for both previews and descriptions. A preview-resolution error retains readable shader fields and any completed description. Source tags are only read. The geometry helper, JMS reconstruction, export exclusions, import preferences and preview node builder are unchanged.

## Inspection

The existing **H3 shader source - [asset]** Text Editor datablock contains the full manifest, including descriptions and unassigned shader records. Render materials link to that datablock through `h3_shader_manifest`. Source diagnostics also appear in **H3 material report - [asset]** for constructed previews. Descriptions are not reconstructed from Blender nodes.

## Tests and package

The shader workflow on `feature/h3-material-provenance` runs the existing helper, geometry, preference, preview and packed-image checks plus source-description tests. Additional synthetic Blender checks cover whole-import metadata retention, distinct material identities, shared image reuse, source versus preview transforms, export exclusions, rollback and saved text persistence.

The workflow packages version 1.9.27 as `Foundry-H3-shaders-test-1.9.27`. The artifact wrapper contains `io_scene_foundry_h3_shaders_test.zip` for Install from Disk and its checksum. It does not deploy Pages or update the normal extension feed.

These checks are not real H3EK imports, Reach Tool compilation, or in-game material comparisons.
