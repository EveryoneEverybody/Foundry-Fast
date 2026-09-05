# Halo 3 object import

An experimental import path for H3 editing-kit objects in a Reach Foundry project. It does not convert a complete game object into a working Reach biped, weapon or vehicle.

The existing Reach importer and exporter are unchanged. The new command is **File > Import > Halo 3 Object (Foundry Experimental)**. F3 also finds **Import Halo 3 Object (Experimental)**.

## First test

Use the **Test Halo 3 object importer** Actions workflow on `feature/h3-object-import`. Its `Foundry-H3-test-1.9.24` artifact contains an installable extension ZIP and checksum. The artifact wrapper ZIP must be extracted first. Install the inner `io_scene_foundry_h3_test.zip` through Blender's Install from Disk command. Avoid enabling two copies of Foundry from different extension repositories.

This test workflow does not deploy GitHub Pages. Running the existing Pages-only build will not bundle the H3 helper.

Keep a Reach project active, start an empty scene, and choose an H3EK `.crate`, `.scenery` or `.model` file. Leave **Reference Only** enabled for the first test. The source tags directory is detected from the file's `tags` ancestor; a manual path is available for nonstandard folder names.

The bundled Windows helper is selected automatically. **Extraction Helper** can override its path. The helper runs as a separate process and only reads source tags. Its outputs go to a new `foundry_h3_*` temporary directory, outside H3EK's tags directory. An already extracted `asset.h3asset.json` can be imported through the same command without running the helper again.

An animated viewport header displays the current construction stage and elapsed time. During native extraction it indicates that the helper process is still running, not proof of continuing decoder progress. Esc cancels the helper and removes newly created Blender datablocks. A single large mesh operation can still block Blender until that operation finishes.

## Included in this pass

- Object-to-model dependency resolution for scenery, crates, bipeds, vehicles, weapons, equipment and device machines/controls. Direct `.model` and `.render_model` inputs are accepted too.
- Reconstructed render meshes, geometric normals, UV channels, skin weights, bind skeleton and markers.
- Separate mesh groups for decoded regions, permutations and LOD labels. LOD labels are retained as metadata rather than silently mapped to a Reach setting.
- Reconstructed collision geometry, separated by rigid bone attachment.
- Box, sphere and convex physics reference shapes. These always remain in an excluded collection, even with Reference Only disabled.
- Independent material slots with source metadata. Ambiguous shader basenames remain unresolved. Foreign shader paths never populate Reach's Halo Shader Path field.
- An import report in Blender's Text Editor, plus reconstructed JMS source files beside the extraction JSON.

The H3 root collection stores the source tag, dependency references, extraction path and report name. Skeleton node names and creation order are retained; the H3 render-model path is not installed as a Reach node-order source.

## Not included yet

Shader/bitmap translation, normal-map textures, animation import, control-rig generation, model-variant selection, child-object assembly, gameplay field conversion, special collision surface semantics and damage behavior are not implemented in this pass.

All decoded render permutations are imported. UVW W coordinates and marker permutation filters are not represented by this bridge. The decoder reconstructs topology; the original editable topology is not guaranteed. Source JMS is an extraction, not a byte-exact copy of a tag.

Physics is reference geometry, not a finished Reach physics model. Body mass, inertia, regions, simulation constraints and vehicle handling are not translated. Decoded capsules, ragdolls and hinges remain in `physics.jms`; they are not instantiated by the Blender builder. Additional physics fields outside the decoder's JMS representation remain in the original source tag only.

Materials are placeholders. Assign valid Reach shader paths before an export test. Disabling Reference Only removes the root collection's export exclusion; it does not certify the asset as ready to compile. Real H3EK imports and a Reach Tool/in-game round trip still require testing on local game data.

## Implementation

`tools/h3_object_bridge` is a small Rust executable using Zoephie's `blam-tags` fork at commit `5d0509fb75eadb96ac7774542ca0b2c10aed7b00`. The pinned decoder supplies geometry extraction. No source game tags or game assets are included.

The bridge writes a versioned JSON description with explicit JMS-times-100 units and WXYZ quaternions. Blender uses Foundry's existing import scale and forward-axis helpers. JSON is validated before construction. There is no H3 ManagedBlam load inside Blender and no write path into H3 tags.

The dependency remains separate from the addon. Its redistribution terms need to be settled before a public release of the helper; the pinned dependency does not declare a license in its Cargo manifest or root file listing.

## Tests

- Rust helper compilation and unit tests on Windows.
- Python validation tests for skeletons, indices, non-finite values, material partitions, separate permutations, ambiguous shader names and collision ownership.
- Blender 5.2.1 construction smoke tests using synthetic geometry and minimal Foundry property stubs. These cover scale, forward rotation, bone parenting, skinning, markers, material separation, physics references, rollback and operator registration.

The smoke test does not initialize ManagedBlam, use shipped H3 data, or compile anything through Reach Tool.
