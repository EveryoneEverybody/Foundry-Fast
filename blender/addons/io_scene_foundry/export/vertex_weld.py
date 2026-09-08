"""Vertex equivalence used by the native geometry exporter, without Blender state."""
import numpy as np


def stable_unique_rows_with_epsilon(arrays, epsilon):
    loop_data = arrays[0] if len(arrays) == 1 else np.hstack(arrays)
    quantized = np.rint(loop_data / epsilon).astype(np.int64)
    _, first_indices, inverse = np.unique(quantized, axis=0, return_index=True, return_inverse=True)
    order = np.argsort(first_indices)
    new_indices = first_indices[order].astype(np.int32)
    remap = np.empty(order.size, dtype=np.int32)
    remap[order] = np.arange(order.size, dtype=np.int32)
    return new_indices, remap[inverse].astype(np.int32)


def render_weld_components(positions, normals, texcoords, lighting_texcoords, vertex_colors,
                           bone_indices, bone_weights):
    arrays = [positions]
    if normals is not None:
        arrays.append(normals)
    if texcoords is not None:
        arrays.extend(texcoords)
    if lighting_texcoords is not None:
        arrays.append(lighting_texcoords)
    if vertex_colors is not None:
        arrays.extend(vertex_colors)
    if bone_weights is not None:
        # Coincident corners can belong to separate moving parts or have distinct
        # blends. Compare the actual exported palette indices and weight bytes.
        arrays.extend((bone_indices, bone_weights))
    return arrays
