"""Read the native authoring dependency roles needed by reusable object roots."""
from pathlib import Path

from .paths import digest


ROLES = {'model':'object.model', 'render_model':'model.render', 'collision_model':'model.collision',
         'physics_model':'model.physics', 'model_animation_graph':'model.animation',
         'shader':'render.material', 'shader_decal':'render.material', 'bitmap':'shader.bitmap',
         'render_method_definition':'shader.definition', 'render_method_option':'shader.option',
         'render_method_template':'shader.template', 'pixel_shader':'shader.program',
         'vertex_shader':'shader.program', 'global_pixel_shader':'shader.program',
         'global_vertex_shader':'shader.program'}


def read(root, tags_root, cache=None):
    from io_scene_foundry.managed_blam import Tag
    tags_root=Path(tags_root).resolve(strict=True)
    cache=cache if cache is not None else {}
    queue=[root];seen=set();files={};edges=[];failures=[];deferred=[]
    while queue:
        path=queue.pop()
        if path in seen:continue
        seen.add(path)
        if path not in cache:
            file=(tags_root/path).resolve(strict=True)
            if not file.is_relative_to(tags_root):raise ValueError('Native object reference escapes tags root')
            references=[]
            with Tag(path=path,tag_must_exist=True) as tag:
                # Definitions declare every available option, including inactive
                # defaults. Actual bitmap bindings and the compiled template
                # belong to the shader; do not traverse inactive declaration
                # branches as though the root consumed them.
                declaration=path.endswith(('.render_method_definition','.render_method_option'))
                for field in ([] if declaration else tag.tag.SelectTagFieldReferencesFast()):
                    if field.Path is None:continue
                    target=str(field.Path.RelativePathWithExtension).replace('\\','/')
                    role=ROLES.get(Path(target).suffix[1:])
                    optional=False
                    if path.endswith('.model') and target==path.rsplit('.',1)[0]+'.imposter_model':
                        policy=tag.tag.SelectField('imposter policy')
                        optional=str(policy.Items[policy.Value].EnumName)=='never'
                    references.append(dict(parent=path,child=target,field=str(field.FieldPath),
                                           role=role,optional=optional))
            cache[path]=dict(file=str(file),sha256=digest(file),references=references)
        entry=cache[path];files[entry['file']]=entry['sha256']
        for reference in entry['references']:
            target=(tags_root/reference['child']).resolve()
            if not target.is_relative_to(tags_root):raise ValueError('Native reference escapes tags root')
            edges.append(reference)
            if reference['optional']:continue
            if not reference['role']:
                deferred.append(dict(reference,disposition='RUNTIME_LATER'))
                continue
            if not target.is_file():
                failures.append(dict(reference,reason='Missing supported native dependency'))
            else:queue.append(reference['child'])
    return dict(output_files=files,edges=edges,unsupported_native_leaves=deferred,failures=failures,
                status='NATIVE_SUPPORTED_CLOSURE_OPENED' if not failures else 'DEFERRED')
