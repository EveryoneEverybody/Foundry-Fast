# H3 materials as Reach nodes

Select an imported H3 object or its armature, then use F3 > Stage H3 Materials as Reach Nodes.
The command stages ordinary `.shader` materials throughout the selected H3 import collection.
Decals and unresolved materials keep their source previews.

Staged materials use the bundled `foundry_reach.shader` group and `Texture Tiling` nodes.
Category choices use names, not H3 option indices. Parameter hookups use socket names and
available UI aliases from the active Reach render-method options. Missing aliases do not
block direct socket matching. Unsupported inputs stay in the source manifest and report.

Source preview materials remain available. Object-linked material slots avoid modifying
shared mesh datablocks or objects outside the selected import. Use F3 > Restore H3 Source
Materials to restore the preview assignments. Edited Reach materials are retained.

Images are packed copies with separate Reach export properties. Compatible uses share a
copy within an import, while color space and bitmap usage differences keep separate copies.
UV transforms remain per texture node. Raw normal pixels feed the native Reach group;
H3 preview-only green inversion is not copied.

The command creates nodes only. It does not write shaders, bitmaps, HLSL, or project files.
Reach shader paths remain blank. Foundry's normal linked-node shader build controls can be
used separately after reviewing the graph and choosing a destination asset. That operation
is not validated by node-staging tests. Animated parameters remain sampled values, not
reconstructed runtime functions. Source material descriptions remain unchanged.

Inspect H3 Reach staging report in the Text Editor for mappings, snapshots, runtime inputs,
missing textures, and defaults. Matching names and socket types are not a rendering-fidelity
claim. Real H3EK imports, Reach Tool compilation, and in-game appearance remain separate tests.
