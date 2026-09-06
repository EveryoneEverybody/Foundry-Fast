"""Scenario render reuse and opt-in static reference snapshots."""
from collections import defaultdict
from contextlib import contextmanager
from functools import wraps
import json
import math
import ntpath
from time import perf_counter

import bpy

from . import utils
from .managed_blam import import_transform
from .tools import importer as backend

PROPERTY = 'tag_scenario_static_reference'
REFERENCE = 'foundry_static_reference'
_originals = []
_runs = []
_scopes = []
_settings = []


def _path(value):
    return ntpath.normcase(ntpath.normpath(str(value)))


def render_key(importer, file, permutations):
    """Key unposed geometry before object colors, functions and attachments."""
    return (_path(importer.tags_dir), _path(file), tuple(sorted(permutations)),
            bool(importer.tag_render), bool(importer.tag_markers),
            bool(importer.from_vert_normals), import_transform.signature(importer.scene_nwo),
            importer.scene_nwo.maintain_marker_axis, importer.apply_materials,
            importer.prefix_setting, bool(importer.corinth))


def _live(value, store):
    try:
        return value is not None and store.get(value.name) == value
    except ReferenceError:
        return False


class Session:
    def __init__(self, importer, enabled=False):
        self.importer = importer
        self.enabled = bool(enabled and not importer.corinth)
        self.depth = 0
        self.object_depth = 0
        self.templates = {}
        self.placements = {}
        self.roots = []
        self.scratch = None
        self.timings = defaultdict(float)
        self.counts = defaultdict(int)
        self.slowest = []
        self.results = []
        self.selection = None

    @contextmanager
    def time(self, label):
        started = perf_counter()
        try:
            yield
        finally:
            self.timings[label] += perf_counter() - started
            self.counts[label] += 1

    @contextmanager
    def isolated(self):
        importer = self.importer
        if self.scratch is None:
            self.scratch = bpy.data.scenes.new('Foundry reference work')
            for name in ('scene_project', 'scale', 'forward_direction', 'maintain_marker_axis', 'asset_type'):
                setattr(self.scratch.nwo, name, getattr(importer.scene_nwo, name))
            self.scratch.nwo.is_main_scene = False
            self.scratch.unit_settings.scale_length = importer.scene.unit_settings.scale_length
        scratch = self.scratch
        scratch.frame_set(importer.scene.frame_current)
        saved = importer.context, importer.scene, importer.scene_collection, importer.build_control_rig
        _settings.append((importer.scene_nwo, importer.scene_nwo_export))
        try:
            with bpy.context.temp_override(scene=scratch, view_layer=scratch.view_layers[0]):
                importer.context = bpy.context
                importer.scene = scratch
                importer.scene_collection = scratch.collection
                importer.build_control_rig = False
                yield scratch
        finally:
            importer.context, importer.scene, importer.scene_collection, importer.build_control_rig = saved
            _settings.pop()

    def close(self):
        for collection in self.templates.values():
            if _live(collection, bpy.data.collections):
                backend.remove_collection_hierarchy(collection)
        self.templates.clear()
        self.placements.clear()
        if _live(self.scratch, bpy.data.scenes):
            for tree in bpy.data.node_groups:
                backend._remap_driver_targets(tree, {self.scratch: self.importer.scene})
            # Failed builds may still own objects in the work scene.
            for child in list(self.scratch.collection.children):
                backend.remove_collection_hierarchy(child)
            bpy.data.scenes.remove(self.scratch)
        self.scratch = None

    def report(self):
        if not self.counts:
            return
        print('\n[Foundry perf] Scenario objects')
        for label, elapsed in self.timings.items():
            print(f'  {label:<30} {elapsed:9.3f}s  ({self.counts[label]} calls)')
        print(f'  render reuse: {self.counts["render cache hits"]} hits, '
              f'{self.counts["render cache misses"]} misses')
        for elapsed, name in sorted(self.slowest, reverse=True)[:10]:
            print(f'  {elapsed:9.3f}s  {name}')
        print('  Timings are inclusive. Material conversion is reported separately.')
        if self.results:
            text = bpy.data.texts.new('Scenario reference report')
            text.use_fake_user = True
            text.write(json.dumps({'format': 'foundry.scenario-reference', 'version': 1,
                                   'assets': self.results}, indent=2))
            print(f'  Static reference report: {text.name}')


def _session(importer):
    session = getattr(importer, '_scenario_reference_session', None)
    if session is None:
        session = Session(importer, bool(_runs and _runs[-1]['static']))
        importer._scenario_reference_session = session
        if _runs:
            _runs[-1]['sessions'].append(session)
    return session


def _driver_targets(id_block):
    ad = getattr(id_block, 'animation_data', None)
    if ad:
        for curve in ad.drivers:
            for variable in curve.driver.variables:
                for target in variable.targets:
                    if target.id is not None:
                        yield target.id


def _material_trees(objects):
    pending = [slot.material.node_tree for ob in objects for slot in ob.material_slots
               if slot.material and slot.material.node_tree]
    seen = set()
    while pending:
        tree = pending.pop()
        if tree in seen:
            continue
        seen.add(tree)
        yield tree
        pending.extend(node.node_tree for node in tree.nodes
                       if node.type == 'GROUP' and node.node_tree)


def _mesh_snapshot(evaluated, depsgraph):
    return bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)


def freeze_collection(root, context, imported_objects, importer):
    """Prepare all snapshots before replacing any source objects."""
    objects = tuple(root.all_objects)
    owned = set(objects)
    removed = {ob for ob in objects if ob.type not in {'MESH', 'LIGHT'}}
    if any(ob.type not in {'MESH', 'LIGHT', 'ARMATURE', 'EMPTY'} or ob.instance_collection
           for ob in objects):
        raise ValueError('Nested instances or non-mesh attachments require the live reference path')
    for tree in _material_trees(objects):
        if any(target in removed for target in _driver_targets(tree)):
            raise ValueError('Material driver references a rig or marker; retained live dependencies')
    for ob in objects:
        if ob.parent is not None and ob.parent not in owned:
            raise ValueError('External parent requires the live reference path')
        for constraint in ob.constraints:
            target = getattr(constraint, 'target', None)
            if target is not None and target not in owned:
                raise ValueError('External constraint requires the live reference path')
        for modifier in ob.modifiers:
            target = getattr(modifier, 'object', None)
            if target is not None and target not in owned:
                raise ValueError('External modifier requires the live reference path')
    depsgraph = context.evaluated_depsgraph_get()
    replacements = {}
    created_data = []
    try:
        for ob in objects:
            if ob.type not in {'MESH', 'LIGHT'}:
                continue
            evaluated = ob.evaluated_get(depsgraph)
            if any(not math.isfinite(value) for row in evaluated.matrix_world for value in row):
                raise ValueError('Non-finite evaluated transform; retained the live reference')
            if ob.type == 'MESH':
                data = _mesh_snapshot(evaluated, depsgraph)
            else:
                data = evaluated.data.copy()
                data.animation_data_clear()
            created_data.append(data)
            snapshot = ob.copy()
            replacements[ob] = snapshot
            snapshot.data = data
            for source_slot, target_slot in zip(ob.material_slots, snapshot.material_slots):
                target_slot.link = source_slot.link
                target_slot.material = source_slot.material
            snapshot.parent = None
            snapshot.constraints.clear()
            snapshot.modifiers.clear()
            snapshot.animation_data_clear()
            snapshot.matrix_world = evaluated.matrix_world.copy()
            # Copy evaluated custom-property values before removing their drivers.
            for name in ob.keys():
                if name != 'nwo' and not name.startswith('_'):
                    value = evaluated.get(name)
                    if isinstance(value, (str, bool, int, float)):
                        snapshot[name] = value
                    elif hasattr(value, 'to_list'):
                        snapshot[name] = value.to_list()
            snapshot.nwo.export_this = False
            snapshot[REFERENCE] = True
            snapshot['reference_source_object'] = ob.name
            snapshot['reference_source_tag'] = root.get('reference_source_tag', '')
            snapshot['reference_frame'] = context.scene.frame_current
        # Linking can fail without changing source membership or data.
        for original, snapshot in replacements.items():
            for collection in original.users_collection:
                collection.objects.link(snapshot)
        updated = [replacements[ob] if ob in replacements else ob
                   for ob in imported_objects if ob not in removed]
        active = context.view_layer.objects.active
        if active in owned:
            context.view_layer.objects.active = replacements.get(active)
        old_data = {ob.data for ob in objects if ob.data is not None}
    except BaseException:
        for snapshot in replacements.values():
            if _live(snapshot, bpy.data.objects):
                bpy.data.objects.remove(snapshot, do_unlink=True)
        for data in created_data:
            backend.remove_orphan_object_data(data)
        raise
    for tree in _material_trees(objects):
        backend._remap_driver_targets(tree, replacements)
    for ob in objects:
        importer.obs_for_props.pop(ob, None)
    bpy.data.batch_remove(ids=objects)
    imported_objects[:] = updated
    for snapshot in replacements.values():
        snapshot.name = snapshot['reference_source_object']
    for data in old_data:
        backend.remove_orphan_object_data(data)
    return len(replacements)


def _patch(owner, name, value):
    _originals.append((owner, name, getattr(owner, name)))
    setattr(owner, name, value)


def prepare():
    # Add options before tools registers the existing operators.
    for operator in (backend.NWO_Import, backend.NWO_OT_ImportFromDrop):
        operator.__annotations__[PROPERTY] = bpy.props.BoolProperty(
            name='Static Reference Objects', default=False,
            description='Import Reach scenario objects as non-exportable static snapshots. '
                        'Keep textures, normals, visible children and the selected pose; omit editable rigs')



def register():
    if _originals:
        return
    original_execute = backend.NWO_Import.execute
    @wraps(original_execute)
    def execute(operator, context):
        run = {'static': getattr(operator, PROPERTY, False), 'sessions': []}
        _runs.append(run)
        try:
            return original_execute(operator, context)
        finally:
            try:
                for session in run['sessions']:
                    session.close()
                    session.report()
            finally:
                _runs.pop()
    _patch(backend.NWO_Import, 'execute', execute)

    original_draw = backend.draw_scenario_import_sections
    @wraps(original_draw)
    def draw(operator, layout, corinth, *args, **kwargs):
        original_draw(operator, layout, corinth, *args, **kwargs)
        show_content = kwargs.get('show_scenario_content', args[3] if len(args) > 3 else False)
        if show_content and not corinth:
            row = layout.row()
            row.enabled = operator.tag_scenario_import_objects
            row.prop(operator, PROPERTY)
    _patch(backend, 'draw_scenario_import_sections', draw)

    original_scene_props, original_export_props = utils.get_scene_props, utils.get_export_props
    _patch(utils, 'get_scene_props', lambda: _settings[-1][0] if _settings else original_scene_props())
    _patch(utils, 'get_export_props', lambda: _settings[-1][1] if _settings else original_export_props())

    original_scenarios = backend.NWOImporter.import_scenarios
    @wraps(original_scenarios)
    def scenarios(importer, *args, **kwargs):
        session = _session(importer)
        session.depth += 1
        _scopes.append(session)
        try:
            with session.time('scenario including BSPs'):
                return original_scenarios(importer, *args, **kwargs)
        finally:
            _scopes.pop()
            session.depth -= 1
    _patch(backend.NWOImporter, 'import_scenarios', scenarios)

    original_objects = backend.NWOImporter.import_object
    @wraps(original_objects)
    def objects(importer, paths, *args, **kwargs):
        session = _session(importer)
        if not session.depth or not isinstance(paths, bpy.types.Object):
            return original_objects(importer, paths, *args, **kwargs)
        started = perf_counter()
        name = paths.nwo.marker_game_instance_tag_name
        session.object_depth += 1
        try:
            with session.time('object hierarchy'):
                if not session.enabled:
                    return original_objects(importer, paths, *args, **kwargs)
                destination = importer.scene_collection
                pending = len(backend.deferred_ops)
                with session.isolated() as scratch:
                    try:
                        root = original_objects(importer, paths, *args, **kwargs)
                        for operation in backend.deferred_ops[pending:]:
                            operation()
                        del backend.deferred_ops[pending:]
                        with session.time('attachment evaluation'):
                            bpy.context.view_layer.update()
                        root[REFERENCE] = True
                        root['reference_source_tag'] = name
                        root['reference_requested_variant'] = paths.nwo.marker_game_instance_tag_variant_name
                        root['reference_resolved_variant'] = root.get('reference_variant', '')
                        root.nwo.type = 'exclude'
                        for ob in root.all_objects:
                            ob.nwo.export_this = False
                        scratch.collection.children.unlink(root)
                        destination.children.link(root)
                        session.roots.append(root)
                    except BaseException:
                        del backend.deferred_ops[pending:]
                        raise
                paths.nwo.export_this = False
                paths[REFERENCE] = True
                return root
        finally:
            session.object_depth -= 1
            session.slowest.append((perf_counter() - started, name))
    _patch(backend.NWOImporter, 'import_object', objects)

    original_render = backend.NWOImporter.import_render_model
    @wraps(original_render)
    def render(importer, file, model_collection, existing_armature, allowed_region_permutations,
               skip_print=False, allow_control_rig=True):
        session = _session(importer)
        cacheable = session.object_depth and existing_armature is None and not importer.build_control_rig
        if not cacheable:
            return original_render(importer, file, model_collection, existing_armature,
                                   allowed_region_permutations, skip_print, allow_control_rig)
        model_collection['reference_render_model'] = str(file)
        model_collection['reference_region_permutations'] = json.dumps(sorted(allowed_region_permutations))
        if session.selection is not None:
            model_collection['reference_variant'] = session.selection[0]
            model_collection['reference_state'] = session.selection[1]
        key = render_key(importer, file, allowed_region_permutations)
        template = session.templates.get(key)
        if _live(template, bpy.data.collections):
            session.counts['render cache hits'] += 1
            with session.time('render hierarchy reuse'):
                collection, mapping = backend.clone_collection_hierarchy(template, model_collection,
                                                                         copy_object_data=True)
                result = list(collection.all_objects)
                armature = next((ob for ob in result if ob.type == 'ARMATURE' and ob.parent is None), None)
                return result, armature
        session.counts['render cache misses'] += 1
        with session.time('render hierarchy build'):
            result = original_render(importer, file, model_collection, existing_armature,
                                     allowed_region_permutations, skip_print, allow_control_rig)
        with session.time('render cache capture'):
            template, _ = backend.clone_collection_hierarchy(model_collection, copy_object_data=True,
                                                             collection_name='Foundry render template')
            session.templates[key] = template
        return result
    _patch(backend.NWOImporter, 'import_render_model', render)

    original_child = backend.NWOImporter.import_child_object
    @wraps(original_child)
    def child(importer, *args, **kwargs):
        session = _session(importer)
        if not session.object_depth:
            return original_child(importer, *args, **kwargs)
        with session.time('child hierarchy'):
            return original_child(importer, *args, **kwargs)
    _patch(backend.NWOImporter, 'import_child_object', child)

    original_get = backend.NWOImporter.get_cached_game_object_collection
    @wraps(original_get)
    def get_collection(importer, tag_path, variant=''):
        session = _session(importer)
        if session.enabled and session.depth and ntpath.splitext(tag_path)[1].lower() in backend.OBJECT_TAG_EXTS:
            collection = session.placements.get((_path(tag_path), variant))
            return collection if _live(collection, bpy.data.collections) else None
        return original_get(importer, tag_path, variant)
    _patch(backend.NWOImporter, 'get_cached_game_object_collection', get_collection)

    original_cache = backend.NWOImporter.cache_game_object_collection
    @wraps(original_cache)
    def cache_collection(importer, collection, tag_path, variant=''):
        session = _session(importer)
        if session.enabled and session.depth and collection.get(REFERENCE):
            session.placements[(_path(tag_path), variant)] = collection
            collection['reference_source_tag'] = tag_path
            collection['reference_requested_variant'] = variant
            return collection
        return original_cache(importer, collection, tag_path, variant)
    _patch(backend.NWOImporter, 'cache_game_object_collection', cache_collection)

    original_merge = backend.merge_collection
    @wraps(original_merge)
    def merge(collection, *args, **kwargs):
        result = original_merge(collection, *args, **kwargs)
        if collection.get(REFERENCE):
            result[REFERENCE] = True
            result.nwo.type = 'exclude'
            for key in ('reference_source_tag', 'reference_requested_variant', 'reference_resolved_variant'):
                result[key] = collection.get(key, '')
        return result
    _patch(backend, 'merge_collection', merge)

    original_materials = backend.setup_materials
    @wraps(original_materials)
    def materials(context, importer, starting_materials, imported_objects, *args, **kwargs):
        session = _session(importer)
        if session.counts:
            utils.print_section('Building Scene Materials')
        result = original_materials(context, importer, starting_materials, imported_objects, *args, **kwargs)
        for root in session.roots:
            row = {'source_tag': root.get('reference_source_tag'),
                   'requested_variant': root.get('reference_requested_variant'),
                   'resolved_variant': root.get('reference_resolved_variant'),
                   'frame': context.scene.frame_current}
            with session.isolated() as scratch:
                scratch.collection.children.link(root)
                try:
                    with session.time('static snapshot'):
                        count = freeze_collection(root, bpy.context, imported_objects, importer)
                    row.update(status='static_snapshot', objects=count)
                except ValueError as error:
                    row.update(status='live_reference_fallback', reason=str(error))
                    utils.print_warning(f'Static reference {row["source_tag"]}: {error}')
                finally:
                    scratch.collection.children.unlink(root)
            session.results.append(row)
        session.roots.clear()
        return result
    _patch(backend, 'setup_materials', materials)

    original_placements = backend.ScenarioTag.objects_to_blender
    @wraps(original_placements)
    def placements(tag, *args, **kwargs):
        if not _scopes:
            return original_placements(tag, *args, **kwargs)
        session = _scopes[-1]
        with session.time('placement construction'):
            result = original_placements(tag, *args, **kwargs)
        if session.enabled:
            for ob in result[0]:
                ob.nwo.export_this = False
                ob[REFERENCE] = True
        return result
    _patch(backend.ScenarioTag, 'objects_to_blender', placements)

    original_variant = backend.ModelTag.get_variant_regions_and_permutations
    @wraps(original_variant)
    def variants(tag, variant, state):
        result = original_variant(tag, variant, state)
        if _scopes:
            _scopes[-1].selection = (variant, state)
        return result
    _patch(backend.ModelTag, 'get_variant_regions_and_permutations', variants)

    for owner, name, label in ((backend.ObjectTag, 'functions_to_blender', 'object function nodes'),
                               (backend.RenderModelTag, '_create_armature', 'armature construction')):
        original = getattr(owner, name)
        def timed(self, *args, _original=original, _label=label, **kwargs):
            if not _scopes:
                return _original(self, *args, **kwargs)
            with _scopes[-1].time(_label):
                return _original(self, *args, **kwargs)
        _patch(owner, name, timed)


def unregister():
    for owner, name, original in reversed(_originals):
        setattr(owner, name, original)
    _originals.clear()
    for operator in (backend.NWO_Import, backend.NWO_OT_ImportFromDrop):
        operator.__annotations__.pop(PROPERTY, None)
