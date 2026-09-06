"""Construct non-exportable H3 BSP references and authored AI overlays."""
import base64
import json
import hashlib
from collections import Counter
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

from ..managed_blam import import_transform
from .material_builder import PreviewBuilder
from .materials import bsp_material_issues
from .scenario_content_builder import ContentBuilder
from . import scenario_scene as source


class ScenarioBuildSession(ContentBuilder):
    def __init__(self, context, data, inventory, directory, material_manifest=None,
                 import_hints=True, import_points=True, flip_normal_green=True, *,
                 import_objects=False, import_content=False, tags_root=None, object_helper=None,
                 object_assets=None, preview_materials=True):
        self.context = context
        self.scene = data
        self.inventory = inventory
        self.directory = Path(directory)
        self.scale = import_transform.scale_factor(context.scene.nwo)
        self.rotation = import_transform.rotation_matrix(context.scene.nwo)
        self.created = []
        self.warnings = []
        self.root = None
        self.shader_source = None
        self.material_manifest = material_manifest
        self.material_report = []
        self.import_objects = import_objects
        self.import_content = import_content
        self.tags_root = tags_root
        self.object_helper = object_helper
        self.object_assets = object_assets
        self.preview_materials = preview_materials
        self.flip_normal_green = flip_normal_green
        self.content_groups = {}
        self.templates = {}
        self.preview = PreviewBuilder(material_manifest, self.directory, self.remember, flip_normal_green) if material_manifest else None
        self.import_hints = import_hints
        self.import_points = import_points
        self.counts = {'bsp_meshes': 0, 'bsp_placements': 0, 'sectors': 0, 'rails': 0, 'firing_positions': 0, 'script_points': 0}
        self.selected = tuple(context.selected_objects)
        self.active = context.view_layer.objects.active

    def remember(self, store, item):
        self.created.append((store, item))
        return item

    def collection(self, name, parent):
        value = self.remember(bpy.data.collections, bpy.data.collections.new(name))
        value.nwo.type = 'exclude'
        value['h3_reference_only'] = True
        parent.children.link(value)
        return value

    def object(self, name, data, parent, role, address):
        value = self.remember(bpy.data.objects, bpy.data.objects.new(name, data))
        parent.objects.link(value)
        value.nwo.export_this = False
        value['h3_scenario_source'] = self.scene['source_tag']
        value['h3_source_address'] = address
        value['h3_source_role'] = role
        value.hide_render = role != 'bsp_render'
        return value

    def text(self, name, data):
        value = self.remember(bpy.data.texts, bpy.data.texts.new(name))
        # Blender Text insertion is costly for enormous single lines. JSON
        # whitespace changes neither source values nor strings within records.
        value.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',\n', ':')))
        value.use_fake_user = True
        return value

    def material(self, record, bsp, slot, faces=0):
        material = self.remember(bpy.data.materials, bpy.data.materials.new(f'H3 {Path(record["name"]).name}'))
        material['h3_source_bsp'] = bsp['source_tag']
        material['h3_source_material_slot'] = slot
        material['h3_source_material_record'] = json.dumps(record)
        material.nwo.shader_path = ''
        material.diffuse_color = (.45, .45, .45, 1)
        issues = bsp_material_issues(record, self.material_manifest)
        result = None
        shader = record.get('source_shader')
        if shader:
            material['h3_source_shader'] = shader
            if self.preview:
                material['h3_shader_manifest'] = self.shader_source.name
                result = self.preview.build(material)
                if result['status'] != 'approximate_preview':
                    issues.append(('blender_preview', '; '.join(result['diagnostics'])))
        report = dict(bsp=bsp['source_tag'], slot=slot, name=record['name'], source_shader=shader,
                      source_triangle_count=faces, preview=result, issues=[dict(stage=s, message=m) for s,m in issues])
        self.material_report.append(report)
        material['h3_bsp_material_diagnostics'] = json.dumps(report)
        for stage, message in issues:
            diagnostic = f"BSP material {bsp['source_tag']} slot {slot} ({faces} source triangles), {shader or record['name']} [{stage}]: {message}"
            self.warnings.append(diagnostic)
            print(diagnostic, flush=True)
        return material

    def mesh(self, record, materials, bsp, collection):
        vertices = record['vertices']
        if any(v['weights'] for v in vertices):
            raise ValueError('Skinned BSP definition retained in source data, not flattened')
        uv_count = max((len(v['uvs']) for v in vertices), default=0)
        if uv_count > 8:
            raise ValueError('BSP definition exceeds eight Blender UV maps')
        mesh = self.remember(bpy.data.meshes, bpy.data.meshes.new(f"bsp_{bsp['bsp_index']}_mesh_{record['id']}"))
        mesh.from_pydata([Vector(v['position']) * self.scale for v in vertices], [],
                         [t['vertices'] for t in record['triangles']])
        mesh.update()
        for material in materials:
            mesh.materials.append(material)
        needs_none = any(t['material'] == -1 for t in record['triangles'])
        if needs_none:
            blank = self.remember(bpy.data.materials, bpy.data.materials.new('H3 unassigned BSP surface'))
            blank.nwo.shader_path = ''
            mesh.materials.append(blank)
        mesh.polygons.foreach_set('material_index', [t['material'] if t['material'] >= 0 else len(materials) for t in record['triangles']])
        mesh.polygons.foreach_set('use_smooth', [True] * len(mesh.polygons))
        if vertices:
            mesh.normals_split_custom_set_from_vertices([v['normal'] for v in vertices])
        original_normals = mesh.attributes.new('h3_source_normal', 'FLOAT_VECTOR', 'POINT')
        original_normals.data.foreach_set('vector', [n for v in vertices for n in v['normal']])
        source_material = mesh.attributes.new('h3_source_material_slot', 'INT', 'FACE')
        source_material.data.foreach_set('value', [t['material'] for t in record['triangles']])
        for uv_index in range(uv_count):
            layer = mesh.uv_layers.new(name='UVMap' if uv_index == 0 else f'UVMap.{uv_index:03}')
            uv_values = [(v['uvs'][uv_index] if uv_index < len(v['uvs']) else [0., 0., 0.]) for v in vertices]
            layer.data.foreach_set('uv', [n for loop in mesh.loops for n in uv_values[loop.vertex_index][:2]])
            # Keep the source W component and missing-channel distinctions.
            w = mesh.attributes.new(f'h3_uv_w_{uv_index}', 'FLOAT', 'POINT')
            w.data.foreach_set('value', [v[2] for v in uv_values])
        counts = mesh.attributes.new('h3_uv_channel_count', 'INT', 'POINT')
        counts.data.foreach_set('value', [len(v['uvs']) for v in vertices])
        color = mesh.color_attributes.new(name='Color', type='FLOAT_COLOR', domain='POINT')
        color.data.foreach_set('color', [n for v in vertices for n in (*v['color'], 1.)])
        mesh.nwo.mesh_type = '_connected_geometry_mesh_type_default'
        mesh['h3_source_bsp'] = bsp['source_tag']
        mesh['h3_source_definition'] = record['id']
        self.counts['bsp_meshes'] += 1
        return mesh

    def trs(self, row, pivot=False):
        prefix = 'pivot_' if pivot else ''
        return Matrix.LocRotScale(Vector(row[prefix + 'position']) * self.scale,
                                  Quaternion(row[prefix + 'rotation']).normalized(),
                                  Vector((row[prefix + 'scale'],) * 3))

    def bsp_steps(self, entry):
        path = source.within(self.directory, entry['geometry'])
        bsp = source.validate_bsp(source.checked_json(path), entry['source_tag'], entry['index'])
        name = Path(bsp['source_tag']).stem
        collection = self.collection(f"{entry['index']:02d}_{name}", self.root)
        collection['h3_source_bsp'] = bsp['source_tag']
        collection['h3_source_bsp_index'] = entry['index']
        render = self.collection('Render', collection)
        auxiliary = self.collection('BSP auxiliary geometry', collection)
        materials = []
        uses = Counter(t['material'] for ob in bsp['objects'] if ob['kind'] == 'mesh' for t in ob['triangles'])
        for i, row in enumerate(bsp['materials']):
            materials.append(self.material(row, bsp, i, uses[i]))
            yield f"BSP {entry['index']}: material {i + 1}/{len(bsp['materials'])}"
        definitions = {}
        for record in bsp['objects']:
            if record['kind'] == 'mesh' and not record.get('xref_path'):
                try:
                    definitions[record['id']] = self.mesh(record, materials, bsp, collection)
                except ValueError as error:
                    self.warnings.append(f"{bsp['source_tag']} definition {record['id']}: {error}")
            yield f"BSP {entry['index']}: definition {record['id']}"
        worlds = {}
        unsupported_parents = set()
        for row in source.placement_order(bsp['instances']):
            parent = Matrix.Identity(4) if row['parent'] == -1 else worlds[row['parent']]
            worlds[row['id']] = parent @ self.trs(row)
            address = f"structure bsps[{entry['index']}]/decoded instances[{row['id']}]"
            if row['inheritance_flag'] != 0 or row['bone_groups'] or row['parent'] in unsupported_parents:
                unsupported_parents.add(row['id'])
                self.warnings.append(address + ': unsupported inheritance or bone groups, not drawn')
                continue
            if row['object'] == -1:
                continue
            record = bsp['objects'][row['object']]
            aux = row['name'].startswith(('+', '@')) or record['kind'] != 'mesh' or bool(record.get('xref_path'))
            ob = self.object(row['name'], definitions.get(row['object']), auxiliary if aux else render,
                             'bsp_auxiliary' if aux else 'bsp_render', address)
            ob.matrix_world = self.rotation @ worlds[row['id']] @ self.trs(row, pivot=True)
            ob['h3_source_instance'] = json.dumps(row)
            ob['h3_source_bsp'] = bsp['source_tag']
            ob['h3_source_definition'] = row['object']
            if ob.data is None:
                ob.empty_display_type = 'SPHERE' if record['kind'] == 'sphere_marker' else 'PLAIN_AXES'
                ob.empty_display_size = max(.1 * self.scale, record.get('radius', 2.) * self.scale)
                if record['kind'] != 'sphere_marker':
                    self.warnings.append(address + ': definition is an unresolved reference or unsupported payload, shown as an empty')
            ob.hide_set(aux)
            self.counts['bsp_placements'] += 1
            if self.counts['bsp_placements'] % 64 == 0:
                yield f"BSP {entry['index']}: {self.counts['bsp_placements']} placements"
        # Keep decoded geometry as a source record, including unsupported definitions.
        yield f"Retaining BSP {entry['index']} source geometry"
        text = self.text(f'H3 BSP source - {name}', bsp)
        collection['h3_bsp_manifest'] = text.name
        self.warnings.extend(f"{bsp['source_tag']}: {v}" for v in bsp.get('limitations', []))

    def hints(self):
        yield 'Planning authored hints and points'
        plan = source.hint_plan(self.inventory)
        for kind in ('sectors', 'rails', 'firing_positions', 'script_points'):
            enabled = self.import_hints if kind in ('sectors', 'rails') else self.import_points
            if not enabled:
                continue
            collection = self.collection(kind.replace('_', ' ').title(), self.root)
            for row in plan[kind]:
                destination = self.hint_collection(row, kind, collection)
                # The pinned JMS/ASS decoder multiplies geometry by 100; the
                # inventory keeps raw world units. Use Foundry's same conversion.
                points = [import_transform.position(p, scene_nwo=self.context.scene.nwo) for p in row['points']]
                curve = None
                if len(points) > 1:
                    curve = self.remember(bpy.data.curves, bpy.data.curves.new(row['name'], 'CURVE'))
                    curve.dimensions = '3D'
                    curve.resolution_u = 1
                    curve.bevel_depth = 1.5 * self.scale
                    curve.bevel_resolution = 0
                    spline = curve.splines.new('POLY')
                    spline.points.add(len(points) - 1)
                    for point, value in zip(spline.points, points):
                        point.co = (*value, 1.)
                    spline.use_cyclic_u = row['closed']
                ob = self.object(row['name'], curve, destination, kind, row['address'])
                ob['h3_source_hint'] = json.dumps(row)
                ob.show_in_front = True
                ob.color = (0.1, .85, 1., 1.) if kind == 'sectors' else (1., .55, .05, 1.)
                if curve is None:
                    ob.location = points[0]
                    ob.empty_display_type = 'PLAIN_AXES' if kind == 'firing_positions' else 'ARROWS'
                    ob.empty_display_size = 5. * self.scale
                self.counts[kind] += 1
                if self.counts[kind] % 64 == 0:
                    yield f'{kind}: {self.counts[kind]}'
        self.warnings.extend(f"{r['address']}: {r['reason']}" for r in plan['diagnostics'])
        text = self.text('H3 authored hint report', plan)
        self.root['h3_hint_report'] = text.name

    def steps(self):
        self.root = self.collection('H3 ' + Path(self.scene['source_tag']).stem, self.context.scene.collection)
        self.root['h3_source_tag'] = self.scene['source_tag']
        self.root['h3_import_kind'] = 'scenario_reference'
        self.root['h3_coordinate_scale'] = 100. * self.scale
        self.root['h3_coordinate_encoding'] = 'source_world_units_unmodified'
        self.root['h3_display_scale_mode'] = self.context.scene.nwo.scale
        self.root['h3_display_forward'] = self.context.scene.nwo.forward_direction
        if self.preview:
            self.shader_source = self.text('H3 shader source - ' + self.root.name, self.preview.manifest)
            self.root['h3_shader_manifest'] = self.shader_source.name
        if self.import_objects or self.import_content:
            yield from self.content_steps()
        for entry in self.scene['bsp_entries']:
            if entry['status'] == 'extracted':
                yield from self.bsp_steps(entry)
            elif entry['status'] == 'error':
                self.warnings.extend(f"BSP {entry['index']}: {e}" for e in entry['diagnostics'])
        if self.import_hints or self.import_points:
            yield from self.hints()
        self.root['h3_scenario_manifest'] = self.text('H3 scenario source - ' + self.root.name, self.inventory).name
        self.root['h3_scene_manifest'] = self.text('H3 scene source - ' + self.root.name, self.scene).name
        chunks = []
        if self.inventory['version'] == 2:
            for chunk in self.inventory['chunks']:
                content = self.inventory.chunk_bytes(chunk)
                text = self.text(f"H3 inventory chunk {len(chunks):04d} - {self.root.name}",
                                 base64.encodebytes(content).decode('ascii'))
                chunks.append(dict(chunk, encoding='gzip+base64', text=text.name,
                                   sha256=hashlib.sha256(content).hexdigest()))
                yield f"Retaining source inventory: {len(chunks)}/{len(self.inventory['chunks'])} chunks"
            self.root['h3_packed_inventory'] = self.text('H3 packed inventory index - ' + self.root.name, chunks).name
            self.counts['inventory_records'] = self.inventory['record_count']
            self.counts['inventory_chunks'] = len(chunks)
        blobs = []
        for row in source.inspection.data_records(self.inventory):
            if row['kind'] == 'data':
                content = source.within(self.directory, row['file']).read_bytes()
                if len(content) != row['bytes']:
                    raise ValueError('Source data blob changed during import')
                packed = self.text(f"H3 source data {len(blobs):04d} - {self.root.name}", base64.encodebytes(content).decode('ascii'))
                blobs.append({'address': row['address'], 'file': row['file'], 'bytes': len(content), 'encoding': 'base64', 'text': packed.name})
        self.root['h3_packed_data'] = self.text('H3 packed source data index - ' + self.root.name, blobs).name
        self.root['h3_material_report'] = self.text('H3 BSP material report - ' + self.root.name, self.material_report).name
        self.warnings.extend(self.scene.get('limitations', []))
        self.root['h3_scenario_report'] = self.text('H3 scenario import report', {'counts': self.counts, 'diagnostics': self.warnings,
            'coordinates': {'source': 'world units (unmodified)', 'geometry': '100 per world unit',
                            'display_units_per_world_unit': 100. * self.scale,
                            'scale_mode': self.context.scene.nwo.scale, 'forward': self.context.scene.nwo.forward_direction},
            'destination_tags_written': False, 'reference_only': True}).name
        yield 'Scenario reference complete'

    def rollback(self):
        for store, item in reversed(self.created):
            try:
                store.remove(item, do_unlink=True) if store is bpy.data.objects else store.remove(item)
            except (ReferenceError, RuntimeError, TypeError):
                pass
        self.created.clear()
        for ob in self.selected:
            try:
                ob.select_set(True)
            except (ReferenceError, RuntimeError):
                pass
        try:
            self.context.view_layer.objects.active = self.active
        except (ReferenceError, RuntimeError):
            pass
