"""Fast direct path layered on the scenario reference importer."""
from copy import deepcopy
from functools import wraps
from pathlib import Path
from time import perf_counter

import bpy

from . import scenario_reference as reference
from . import scenario_static_direct as direct
from .tools import importer as backend

_originals = []


def _patch(owner, name, value):
    _originals.append((owner, name, getattr(owner, name)))
    setattr(owner, name, value)


def _draw_scenario_sections(operator, layout, corinth, show_template=True, show_zone_set=False,
                            show_sky=False, show_scenario_content=False, show_setup_as_asset=True):
    """Keep the reference option with the other Blender viewing controls."""
    if show_template:
        backend.draw_import_template(operator, layout)

    if show_zone_set or show_sky:
        source_box = layout.box()
        source_box.label(text="Selection")
        if show_zone_set:
            source_box.prop(operator, "tag_zone_set")

    core_box = layout.box()
    core_box.label(text="Core")
    core_box.prop(operator, "tag_bsp_import_geometry")
    core_box.prop(operator, "tag_import_lights")

    reimport_box = layout.box()
    reimport_box.label(text="Game Reimport")
    if show_setup_as_asset:
        setup_row = reimport_box.row()
        setup_row.enabled = not getattr(operator, "force_no_setup_as_asset", False)
        setup_row.prop(operator, "setup_as_asset")
    reimport_col = reimport_box.column(align=True)
    reimport_col.enabled = not operator.tag_bsp_render_only
    reimport_col.prop(operator, "tag_bsp_skip_structure_merge")
    if corinth:
        reimport_col.prop(operator, "tag_bsp_import_havok")
    reimport_col.prop(operator, "tag_import_design")

    view_box = layout.box()
    view_box.label(text="Blender Viewing")
    view_box.prop(operator, "tag_bsp_render_only")
    if show_sky:
        view_box.prop(operator, "tag_sky")
    if show_scenario_content:
        view_box.prop(operator, "tag_scenario_import_objects")
        if not corinth and hasattr(operator, reference.PROPERTY):
            row = view_box.row()
            row.enabled = operator.tag_scenario_import_objects
            row.prop(operator, reference.PROPERTY)
        view_box.prop(operator, "tag_scenario_import_decals")
        view_box.prop(operator, "tag_scenario_import_decorators")
        row = view_box.row()
        row.enabled = operator.tag_scenario_import_decorators
        row.prop(operator, "decorator_lod")
    view_box.prop(operator, "build_blender_materials")
    view_box.prop(operator, "always_extract_bitmaps")


def _function_key(tag):
    path = getattr(tag, "tag_path", None)
    if path is None:
        return None
    return getattr(path, "RelativePathWithExtension", None) or getattr(path, "Filename", None) or str(path)


def register():
    if _originals:
        return

    _patch(backend, 'draw_scenario_import_sections', _draw_scenario_sections)

    original_functions = backend.ObjectTag.functions_to_blender
    @wraps(original_functions)
    def functions(tag, *args, **kwargs):
        if not reference._scopes:
            return original_functions(tag, *args, **kwargs)
        session = reference._scopes[-1]
        if not session.enabled:
            return original_functions(tag, *args, **kwargs)
        key = _function_key(tag)
        if key is None:
            return original_functions(tag, *args, **kwargs)
        cache = getattr(session, 'object_function_cache', None)
        if cache is None:
            cache = session.object_function_cache = {}
        if key in cache:
            session.counts['object function cache hits'] += 1
            return deepcopy(cache[key])
        result = original_functions(tag, *args, **kwargs)
        cache[key] = deepcopy(result)
        session.counts['object function cache misses'] += 1
        return result
    _patch(backend.ObjectTag, 'functions_to_blender', functions)

    original_objects = backend.NWOImporter.import_object
    @wraps(original_objects)
    def objects(importer, paths, existing_armature, pose=None, *args, **kwargs):
        session = reference._session(importer)
        if not (session.enabled and session.depth and isinstance(paths, bpy.types.Object)):
            return original_objects(importer, paths, existing_armature, pose, *args, **kwargs)

        started = perf_counter()
        tag_name = paths.nwo.marker_game_instance_tag_name
        destination = importer.scene_collection
        session.object_depth += 1
        try:
            with session.isolated() as scratch:
                root, reason = direct.try_build(importer, paths, pose, session)
                if root is None:
                    session.counts['direct static fallbacks'] += 1
                    if reason:
                        session.counts[f'direct fallback: {reason}'] += 1
                else:
                    root[reference.REFERENCE] = True
                    root['reference_source_tag'] = tag_name
                    root['reference_requested_variant'] = paths.nwo.marker_game_instance_tag_variant_name
                    root['reference_resolved_variant'] = root.get('reference_variant', '')
                    root.nwo.type = 'exclude'
                    for ob in root.all_objects:
                        ob.nwo.export_this = False
                        ob[reference.REFERENCE] = True
                    scratch.collection.children.unlink(root)
                    destination.children.link(root)
                    paths.nwo.export_this = False
                    paths[reference.REFERENCE] = True
                    session.counts['direct static definitions'] += 1
                    session.results.append({
                        'source_tag': tag_name,
                        'requested_variant': paths.nwo.marker_game_instance_tag_variant_name,
                        'resolved_variant': root.get('reference_variant', ''),
                        'frame': importer.scene.frame_current,
                        'status': 'direct_static',
                        'objects': len([ob for ob in root.all_objects if ob.type in {'MESH', 'LIGHT'}]),
                    })
                    return root
        finally:
            session.object_depth -= 1
            session.slowest.append((perf_counter() - started, tag_name))

        # The normal reference wrapper handles skinned, posed, attached, instanced,
        # or otherwise unsupported definitions and snapshots them after materials.
        return original_objects(importer, paths, existing_armature, pose, *args, **kwargs)
    _patch(backend.NWOImporter, 'import_object', objects)

    original_report = reference.Session.report
    @wraps(original_report)
    def report(session):
        original_report(session)
        if session.counts.get('direct static definitions') or session.counts.get('direct static fallbacks'):
            print(f'  direct static definitions: {session.counts["direct static definitions"]}, '
                  f'fallbacks: {session.counts["direct static fallbacks"]}')
            print(f'  object function reuse: {session.counts["object function cache hits"]} hits, '
                  f'{session.counts["object function cache misses"]} misses')
            fallback_rows = sorted(
                ((count, name.removeprefix('direct fallback: ')) for name, count in session.counts.items()
                 if name.startswith('direct fallback: ')),
                reverse=True,
            )
            for count, reason in fallback_rows[:8]:
                print(f'    {count:4d} fallback: {reason}')
    _patch(reference.Session, 'report', report)


def unregister():
    for owner, name, original in reversed(_originals):
        setattr(owner, name, original)
    _originals.clear()
