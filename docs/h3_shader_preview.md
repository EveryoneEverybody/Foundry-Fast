# H3 shader previews

Test build: 1.9.26. Branch: `feature/h3-shader-import`.

The object importer can now run a second helper for shader metadata and bitmap extraction. The geometry helper, model transforms, collision construction and physics references are unchanged.

## Import

Enable **Material Previews** in **Import Halo 3 Object**. The H3 tags directory still comes from Foundry preferences or the selected source tag. The active Reach project remains the destination project.

**Flip Normal Green** changes the Blender preview nodes, not the extracted image pixels. It defaults on and can be disabled for a comparison import.

Existing `.h3asset.json` imports use a sibling `shader_manifest.json` when present. They do not start shader extraction without an H3 source root. Import the original H3 tag to create a fresh extraction.

## Data and reports

`h3-shader-bridge` reads H3 render methods, selected category/option names, parameter declarations and values, bitmap bindings, sampler settings and animated parameter blobs through the pinned blam-tags reader. Source animation functions are recorded as hex bytes. Preview values are sampled at time zero; named object functions do not have a runtime provider.

The extraction contains `shader_manifest.json`, DDS outputs where supported, and RGBA8 TIFF previews for eligible single-image 2D textures. DDS export follows the decoder's format support; Halo-specific formats may be decoded rather than copied bit-for-bit.

Blender stores the source manifest in **H3 shader source - [asset]** and per-material diagnostics in **H3 material report - [asset]**. Preview images are packed into the blend file. The DDS files remain external extraction outputs.

Materials remain separate. Image reuse is keyed by the full source bitmap path, image index and color/data role. Normal maps and masks do not inherit a color texture's sRGB setting. Shader paths are not assigned to Reach tags automatically.

## Preview coverage

Implemented albedo paths: default, constant color, detail blend, two-change-color and four-change-color. The default detail multiplier is the H3 value, 4.59479. Change-color masks are supported, but object/model variant colors are not supplied automatically.

Standard normal mapping, 0.5 alpha-test cutouts, approximate alpha blending and simple self-illumination are included. Other decoded 2D textures remain accessible as unconnected source nodes.

Lighting, specular lobes, reflections, blend passes and special shader families are not reproductions of Halo's renderer. Unknown options are reported. Source shader inheritance is not flattened. Cubemaps, arrays, multi-image/sprite bitmaps and high-precision previews need separate handling. Material functions are not animated in Blender. Non-sRGB color curves and unsupported sampler combinations are explicitly reported as approximations.

## Reach mapping

The helper reads the destination render-method definition at the same relative path, then matches categories and options by name. Source option numbers are never copied into Reach option slots. Missing or ambiguous matches stay unresolved.

The result is a candidate table, not an export-ready shader recipe. Matching names do not prove matching parameter contracts or equivalent HLSL. No Reach shader, bitmap or render-method tags are created or overwritten by this pass.

The next writer needs parameter/type/default checks, destination bitmap preparation, shader-family handling and actual Reach Tool tests. Blender preview nodes must not be treated as a lossless source for that writer.

## Source references

- blam-tags pinned revision: `5d0509fb75eadb96ac7774542ca0b2c10aed7b00`, `render_method/{choices,walker,cbuffer,types}.rs` and `bitmap/`.
- H3 HLSL revision: `257ca5f9e1149a31dbfb6a7c9141bd232f590e5b`, `hlsl/albedo.fx`, `hlsl/alpha_test.fx`, `hlsl/self_illumination.fx`.
- The cbuffer implementation returns RGBA colors. The walker's ARGB comment does not describe that actual ordering.

Tests use synthetic manifests, images and geometry. They are not an H3EK material fidelity check or a Reach Tool/in-game round trip.
