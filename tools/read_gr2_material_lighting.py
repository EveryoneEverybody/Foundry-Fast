"""Read normal Foundry GR2 emissive annotations; never change source or tags."""
import argparse
from collections import Counter
import ctypes as C
import hashlib
import importlib.util
import json
from pathlib import Path


def read(path, dll_path):
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('granny_lighting_formats', repo/'blender/addons/io_scene_foundry/granny/formats.py')
    f = importlib.util.module_from_spec(spec); spec.loader.exec_module(f)
    dll = C.CDLL(str(dll_path))
    dll.GrannyReadEntireFile.argtypes = [C.c_char_p]; dll.GrannyReadEntireFile.restype = C.POINTER(f.GrannyFile)
    dll.GrannyGetFileInfo.argtypes = [C.POINTER(f.GrannyFile)]; dll.GrannyGetFileInfo.restype = C.POINTER(f.GrannyFileInfo)
    dll.GrannyFreeFile.argtypes = [C.POINTER(f.GrannyFile)]
    handle = dll.GrannyReadEntireFile(str(path).encode())
    if not handle: raise ValueError('Granny could not read input')
    try:
        info = dll.GrannyGetFileInfo(handle).contents
        if not 0 < info.mesh_count < 10000: raise ValueError('Invalid mesh count')
        meshes = []
        for i in range(info.mesh_count):
            mesh = info.meshes[i].contents; topology = mesh.primary_topology.contents
            count = (topology.index_count or topology.index16_count)//3
            arrays = {}
            for j in range(topology.tri_annotation_set_count):
                a = topology.tri_annotation_sets[j]; name = a.name.decode()
                if not name.startswith('bungie_lighting_'): continue
                typ = a.tri_annotation_type[0]; width = max(typ.array_width, 1)
                if (typ.member_type not in (10,19,20) or not 1 <= width <= 4 or
                    a.tri_annotation_type[1].member_type != 0 or a.tri_annotation_count != count or
                    a.tri_annotation_index_count or a.indices_map_from_tri_to_annotation != 1):
                    raise ValueError('Unsupported annotation layout: '+name)
                scalar = {10:C.c_float, 19:C.c_int32, 20:C.c_uint32}[typ.member_type]
                data = C.cast(a.tri_annotations, C.POINTER(scalar))
                arrays[name] = [tuple(data[k*width+n] for n in range(width)) for k in range(count)]
            powers = arrays.get('bungie_lighting_emissive_power')
            if not powers: continue
            variants = Counter()
            for j in range(topology.group_count):
                group = topology.groups[j]
                if not 0 <= group.material_index < mesh.material_binding_count: raise ValueError('Invalid material binding')
                material = mesh.material_bindings[group.material_index].material.contents
                variant_type = material.extended_data.type
                names = [variant_type[n].name.decode() for n in range(2)]
                if names != ['bungie_shader_path','bungie_shader_type']: raise ValueError('Unexpected material identity schema: '+str(names))
                strings = C.cast(material.extended_data.object, C.POINTER(C.c_char_p))
                shader = strings[0].decode().replace('\\','/')+'.'+strings[1].decode()
                for triangle in range(group.tri_first, group.tri_first+group.tri_count):
                    if powers[triangle][0] <= 0: continue
                    fields = tuple((name, arrays[name][triangle]) for name in sorted(arrays))
                    variants[(shader, fields)] += 1
            if variants:
                meshes.append(dict(mesh=mesh.name.decode(), variants=[dict(shader=shader, fields=dict(fields), triangles=n)
                    for (shader, fields), n in variants.items()]))
        return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            dll_sha256=hashlib.sha256(dll_path.read_bytes()).hexdigest(), meshes=meshes,
            mesh_count=info.mesh_count, interpretation='Unique exported mesh triangles; repeated model placements are not expanded')
    finally:
        dll.GrannyFreeFile(handle)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('gr2', type=Path, nargs='+')
    args = parser.parse_args()
    if args.output.exists(): raise ValueError('Use a new report path')
    result = [read(p, args.dll) for p in args.gr2]
    args.output.write_text(json.dumps(result, indent=2))
    for row in result: print(row['path'], len(row['meshes']), 'meshes with positive emissive triangles')
