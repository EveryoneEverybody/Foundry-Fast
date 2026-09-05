# Halo 3 object import

An experimental import path for H3 editing-kit objects in a Reach Foundry project. It does not convert a complete game object into a working Reach biped, weapon or vehicle.

The existing Reach importer and exporter are unchanged. The new command is **File > Import > Halo 3 Object (Foundry Experimental)**. F3 also finds **Import Halo 3 Object (Experimental)**.

## First test

Use the **Test Halo 3 object importer** Actions workflow on `feature/h3-object-import`. Its `Foundry-H3-test-1.9.25` artifact contains an installable extension ZIP and checksum. The artifact wrapper ZIP must be extracted first. Install the inner `io_scene_foundry_h3_test.zip` through Blender's Install from Disk command. Avoid enabling two copies of Foundry from different extension repositories.

This test workflow does not deploy GitHub Pages. Running the existing Pages-only build will not bundle the H3 helper.

Keep a Reach project active, start an empty scene, and choose an H3EK `.crate`, `.scenery` or `.model` file. Leave **Reference Only** enabled for the first test.

### Source settings

Starting in 1.9.25, **Preferences > Add-ons > Foundry > Halo 3 Import (Experimental)** contains the source settings. They are add-on preferences, not per-import options or scene properties.

- **Halo 3 Tags Directory:** the H3EK `tags` directory. Leave blank to detect the nearest `tags` ancestor of the selected source tag. A saved directory also supports nonstandard folder names. A fresh file selector starts in the saved directory when no file path is already set.
- **Extraction Helper Override:** an optional path to `h3-object-bridge.exe`. Leave blank to use the bundled Windows helper.

Save Blender preferences when automatic preference saving is disabled. Close an open tag file selector before browsing for these settings. The import sidebar contains status labels and the Collision Geometry, Physics Reference Shapes, and Reference Only options, with no nested path pickers.

The active Reach root still comes from Foundry's Projects list. An H3 source directory does not need a Projects entry, `project.xml`, `project.root`, or ProjectChooser. The importer does not change the active Reach project. A configured H3 tags directory is authoritative: a selected tag outside that directory reports an error with the preference location rather than silently switching roots.

The helper runs as a separate process and only reads source tags. Its outputs go to a new `foundry_h3_*` temporary directory, outside H3EK's tags directory. An already extracted `asset.h3asset.json` can be imported through the same command without running the helper again.

An animated viewport header displays the current construction stage and elapsed time. During native extraction it indicates that the helper process is still running, not proof of continuing decoder progress. Esc cancels the helper and removes newly created Blender datablocks. A single large mesh operation can still block Blender until that operation finishes.

## Included in this pass

- Object-to-model dependency resolution for scenery, crates, bipeds, vehicles, weapons, equipment and device machines/controls. Direct `.model` and `.render_model` inputs are accepted too.
- Reconstructed render meshes, geometric normals, UV channels, skin weights, bind skeleton and markers.
- Separate mesh groups for decoded regions, permutations and LOD labels. LOD labels are retained as metadata rather than silently mapped to a Reach setting.
- Reconstructed collision geometry, separated by rigid bone attachment.
- Box, sphere and convex physics reference shapes. These always remain in an excluded collection, even with Reference Only disabled.
- Independent material slots with source metadata. Ambiguous shader basenames remain unresolved. Foreign shader paths never populate Reach's Halo Shader Path field.
- An import report in Blender's Text Editor, plus reconstructed JMS source files beside the extraction JSON.

Decoded instance attachments without region/permutation fields remain separate meshes with provisional default labels and an explicit report entry. Their original placement labels are retained.

The H3 root collection stores the source tag, dependency references, extraction path and report name. Skeleton node names and creation order are retained; the H3 render-model path is not installed as a Reach node-order source.

## Not included yet

Shader/bitmap translation, normal-map textures, animation import, control-rig generation, model-variant selection, child-object assembly, gameplay field conversion, special collision surface semantics and damage behavior are not implemented in this pass.

All decoded render permutations are imported. UVW W coordinates and marker permutation filters are not represented by this bridge. The decoder reconstructs topology; the original editable topology is not guaranteed. Source JMS is an extraction, not a byte-exact copy of a tag.

Physics is reference geometry, not a finished Reach physics model. Body mass, inertia, regions, simulation constraints and vehicle handling are not translated. Decoded capsules, ragdolls and hinges remain in `physics.jms`; they are not instantiated by the Blender builder. Additional physics fields outside the decoder's JMS representation remain in the original source tag only.

Materials are placeholders. Assign valid Reach shader paths before an export test. Disabling Reference Only removes the root collection's export exclusion; it does not certify the asset as ready to compile. A Reach Tool/in-game round trip still requires testing on local game data.

## Implementation

`tools/h3_object_bridge` is a small Rust executable using Zoephie's `blam-tags` fork at commit `5d0509fb75eadb96ac7774542ca0b2c10aed7b00`. The pinned decoder supplies geometry extraction. No source game tags or game assets are included.

The bridge writes a versioned JSON description with explicit JMS-times-100 units and WXYZ quaternions. Physics shapes are explicitly node-local and resolve attachments by the physics skeleton's bone names rather than assuming the render skeleton has the same node indices. Blender uses Foundry's existing import scale and forward-axis helpers. JSON is validated before construction. There is no H3 ManagedBlam load inside Blender and no write path into H3 tags.

The dependency remains separate from the addon. Its redistribution terms need to be settled before a public release of the helper; the pinned dependency does not declare a license in its Cargo manifest or root file listing.

## Tests

- Rust helper compilation and unit tests on Windows.
- Python validation tests for skeletons, indices, non-finite values, material partitions, separate permutations, ambiguous shader names and collision ownership.
- Source-setting tests for saved paths, automatic detection without project XML, helper overrides, invalid paths, Reach-source separation, and the absence of import-dialog path widgets.
- Blender 5.2.1 construction smoke tests using synthetic geometry and minimal Foundry property stubs. These cover scale, forward rotation, bone parenting, skinning, markers, material separation, physics references, rollback and operator registration.
- Blender preference integration checks register the real preferences and importer classes with isolated Foundry dependencies and check preference bindings and source resolution.

The smoke tests do not initialize ManagedBlam, use shipped H3 data, exercise interactive file browsers, or compile anything through Reach Tool.

A local 1.9.24 fusion-coil test was reported with visible render parts, collision meshes, markers, an armature and a physics-reference mesh. That visual report does not establish shader conversion or a working Reach gameplay object.
