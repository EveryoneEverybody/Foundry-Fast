"""Deduplicated source semantic edges for modeled object roots.

Only admitted authoring roles are expanded. Additional references remain
visible leaves, never generic recursively copied dependencies.
"""
from pathlib import Path, PurePosixPath

from .model import stable_hash
from .paths import digest


ROLES = {'model': 'object.model', 'render_model': 'model.render',
         'collision_model': 'model.collision', 'physics_model': 'model.physics',
         'animation_graph': 'model.animation'}


def graph(objects, shaders, bitmaps, tags_root):
    tags_root = Path(tags_root).resolve(strict=True)
    nodes, edges, roots = {}, {}, {}
    def node(path, disposition):
        # H3 missing-reference evidence can contain spaces. Generated target
        # namespace restrictions must not erase those authentic source names.
        path = path.replace('\\','/')
        source_path = PurePosixPath(path)
        if source_path.is_absolute() or ':' in path or '\x00' in path or '..' in source_path.parts:
            raise ValueError('Unsafe source closure path: '+path)
        path = source_path.as_posix()
        if path not in nodes:
            file = (tags_root/path).resolve()
            if not file.is_relative_to(tags_root):
                raise ValueError('Closure dependency escapes source root')
            exists = file.is_file()
            nodes[path] = dict(source_tag=path, tag_class=Path(path).suffix[1:],
                source_sha256=digest(file) if exists else None, source_exists=exists,
                disposition=disposition if exists else 'BLOCKING_UNKNOWN')
        return path
    def edge(parent, child, role, disposition):
        child = node(child, disposition)
        key = stable_hash([parent, child, role])
        edges[key] = dict(parent=parent, child=child, semantic_role=role, disposition=disposition)
        return key
    for obj in objects:
        root = node(obj['source_tag'], obj.get('classification', 'NATIVE_REBUILD'))
        ir = obj.get('object_ir', {})
        selected = []
        for field, role in ROLES.items():
            dependency = ir.get(field)
            if dependency:
                parent = root if field == 'model' else ir.get('model') or root
                disposition = 'RUNTIME_LATER' if field == 'animation_graph' and obj.get('animation_policy') != 'SOURCE_DEVICE_JMA_TO_NATIVE_GRAPH' else 'NATIVE_REBUILD'
                selected.append(edge(parent, dependency, role, disposition))
        known = {ir.get(field) for field in ROLES}
        for reference in ir.get('dependency_provenance', []):
            if reference['source_tag'] in known:
                continue
            # The exact source field is the role evidence. It is deliberately
            # not upgraded to an implemented semantic contract by its name.
            selected.append(edge(root, reference['source_tag'],
                                 'untranslated_reference:' + reference['source_field'], 'RUNTIME_LATER'))
        for shader in ir.get('materials', []):
            selected.append(edge(ir.get('render_model') or ir.get('model') or root, shader,
                                 'render.material', 'NATIVE_TRANSFORM'))
            material = shaders.get(shader, {})
            description = material.get('source_description') or {}
            definition = description.get('source_definition') or material.get('definition')
            if isinstance(definition,str) and definition:
                if not definition.endswith('.render_method_definition'):
                    definition += '.render_method_definition'
                selected.append(edge(shader, definition, 'shader.definition', 'NATIVE_TRANSFORM'))
            for category in description.get('categories', []):
                if category.get('option_tag'):
                    selected.append(edge(shader, category['option_tag'],
                                         'shader.option_default:'+category['category'], 'NATIVE_TRANSFORM'))
            for parameter in material.get('parameters', []):
                key = parameter.get('bitmap')
                if key:
                    bitmap = bitmaps.get(key, {})
                    path = bitmap.get('source_tag') or bitmap.get('source_bitmap') or bitmap.get('path') or key.split('#')[0]
                    if not path.endswith('.bitmap'):
                        path += '.bitmap'
                    selected.append(edge(shader, path, 'shader.bitmap:' + parameter['name'], 'NATIVE_REBUILD'))
        selected = sorted(set(selected))
        members = sorted({root} | {edges[e]['parent'] for e in selected} | {edges[e]['child'] for e in selected})
        roots[root] = dict(nodes=members, edges=selected,
                          fingerprint=stable_hash(dict(nodes=[nodes[n] for n in members],
                                                       edges=[edges[e] for e in selected])))
    return dict(format='foundry.semantic-asset-closure', nodes=nodes, edges=edges, roots=roots)
