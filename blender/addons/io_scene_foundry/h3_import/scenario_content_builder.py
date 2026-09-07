"""Organize source content and instance the existing H3 object builder's output."""
import json
import re
import time
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

from ..managed_blam import import_transform
from . import scenario_content, scenario_objects
from .builder import BuildSession
from .core import load_payload
from .scenario_frames import FrameResolver, marker_matrix, multiply, inverse_rigid
from .scenario_reporting import summarize, messages, measured


class ContentBuilder:
    def object_template(self, key, assets, active, diagnostics):
        if key in self.templates: return self.templates[key]
        if key in active or len(active) >= 32:
            diagnostics.append(f'Child attachment cycle or depth limit at {key}')
            self.profile.counts['child_attachment_fallback'] += 1
            return None
        active = active | {key}
        source, variant = key
        asset = assets.get(source, {})
        payload = self.source_payloads.get(source)
        template = None
        session = None
        try:
            if payload:
                session = BuildSession(self.context, payload, asset['asset'], True,
                    self.preview_materials, self.flip_normal_green, source_axes=True, variant=variant)
                for phase in self.profile.steps('Blender object-template construction', session.build()):
                    yield f'Object template {source}: {phase}'
                template = session.root
                self.context.scene.collection.children.unlink(template)
                for ob in template.all_objects:
                    ob.nwo.export_this = False
                    ob['h3_reference_only'] = True
                def exclude(collection):
                    collection.nwo.type = 'exclude'
                    for child in collection.children: exclude(child)
                exclude(template)
                self.created.extend(session.created); session.created.clear()
                diagnostics.extend(session.warnings)
                self.counts['object_templates'] += 1
                attachments, warnings = scenario_objects.children(payload, variant)
                diagnostics.extend(warnings)
                for child in attachments:
                    child_key = (child['source_tag'], child.get('variant', ''))
                    child_diagnostics = []
                    child_template = yield from self.object_template(child_key, assets, active, child_diagnostics)
                    diagnostics.extend(child_diagnostics)
                    try:
                        if child_template is None: raise ValueError('Child source template unavailable')
                        child_payload = self.source_payloads[child_key[0]]
                        matrix = Matrix(multiply(marker_matrix(payload, child.get('parent_marker')),
                                                 inverse_rigid(marker_matrix(child_payload, child.get('child_marker')))))
                        matrix.translation *= 100. * self.scale
                        with self.profile.span('child attachment construction'):
                            ob = self.object(Path(child['source_tag']).stem, None, template, 'child_attachment', '')
                            ob.instance_type = 'COLLECTION'; ob.instance_collection = child_template
                            ob.matrix_world = matrix; ob.hide_render = False
                            ob['h3_source_tag'] = child['source_tag']
                            ob['h3_source_attachment'] = json.dumps(dict(child, parent_source_tag=source))
                            self.profile.counts['child_attachments_resolved'] += 1
                    except (KeyError, ValueError, TypeError) as error:
                        diagnostics.append(f"Child attachment {source} objects[{child['source_index']}] -> {child['source_tag']}: {error}")
                        self.profile.counts['child_attachment_fallback'] += 1
            elif source and asset.get('status') != 'semantic':
                diagnostics.append(f'Source object geometry unavailable: {source}; placement shown as a reference marker')
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            if session and session.created: session.rollback()
            diagnostics.append(f'Object construction failed: {source}: {error}')
        finally:
            if session and session.created: session.rollback()
        self.templates[key] = template
        return template

    def content_collection(self, key):
        if key not in self.content_groups:
            self.content_groups[key] = self.collection(key, self.root)
        return self.content_groups[key]

    def content_transform(self, position, rotation=(0., 0., 0.), scale=1.):
        yaw, pitch, roll = rotation
        return self.rotation @ Matrix.LocRotScale(Vector(position) * (100. * self.scale),
            Euler((roll, -pitch, yaw), 'ZYX').to_quaternion(), Vector((scale,) * 3))

    def hint_collection(self, row, kind, fallback):
        if not self.import_content:
            return fallback
        address = row['address']
        if kind == 'firing_positions':
            match = re.match(r'zones#\d+\[(\d+)\]', address)
            if match:
                return self.content_groups.get(f"zone:{match[1]}/area:{row.get('area_index')}", self.content_groups.get('zone:' + match[1], fallback))
        if kind == 'script_points':
            match = re.match(r'scripting data#\d+\[(\d+)\]/point sets#\d+\[(\d+)\]', address)
            if match:
                return self.content_groups.get(f'point-set:{match[1]}:{match[2]}', fallback)
        return fallback

    def content_steps(self):
        yield 'Planning scenario objects, folders and authored content'
        content = scenario_content.plan(self.inventory)
        assets = self.object_assets
        if assets is None and self.tags_root and self.object_helper and self.import_objects:
            extraction_started = time.perf_counter()
            assets = yield from self.profile.steps('unique placed-object extraction wall time',
                scenario_objects.extract(content, self.tags_root, self.directory, self.object_helper, self.preview_materials))
            self.profile.elapsed('unique source extraction elapsed including helper and UI waits', time.perf_counter()-extraction_started)
        assets = assets or {}
        self.profile.counts['unique_source_tags'] = len(assets)
        self.profile.counts['unresolved_dependencies'] = sum(r.get('status') == 'error' for r in assets.values())
        self.profile.counts['stored_poses_applied'] = 0
        self.source_payloads = {}
        self.semantic_sources = {}
        for source, asset in assets.items():
            if asset.get('status') == 'semantic':
                semantic = scenario_objects.load_semantic(asset['semantic'], source)
                self.semantic_sources[source] = self.text('H3 semantic source - ' + Path(source).stem, semantic).name
            if asset.get('status') == 'extracted':
                try:
                    payload = load_payload(asset['asset'])
                    if payload['source_tag'] != source: raise ValueError('Placed extraction source identity mismatch')
                    self.source_payloads[source] = payload
                except (OSError, ValueError, KeyError, TypeError) as error:
                    asset['diagnostics'] = list(asset.get('diagnostics', [])) + [str(error)]
        self.frame_resolver = FrameResolver(scenario_content.ContentIndex(self.inventory, scenario_content.CONTENT_ROOTS),
                                            content['placements'], self.source_payloads)
        with self.profile.span('reference-frame resolution and content planning'):
            content = scenario_content.plan(self.inventory, self.frame_resolver)
        self.content_plan = content
        records = {r['key']: r for r in content['groups']}
        visiting = set()
        def create(key):
            if key in self.content_groups:
                return self.content_groups[key]
            if key not in records:
                return self.content_collection(key)
            row = records[key]
            visiting.add(key)
            if row['parent'] in visiting or len(visiting) >= 96:
                parent = self.content_collection('Unresolved group hierarchy')
                content['diagnostics'].append(dict(address=row['address'], reason='Cyclic or excessively deep source group hierarchy; source parent retained'))
            else:
                parent = create(row['parent'])
            visiting.remove(key)
            collection = self.collection(row['name'], parent)
            collection['h3_source_group'] = json.dumps(row)
            collection['h3_source_address'] = row['address']
            self.content_groups[key] = collection
            return collection
        if self.import_content:
            for i, key in enumerate(records):
                create(key)
                if i % 32 == 0: yield f'Scenario collections: {i + 1}/{len(records)}'
        else:
            for key in records:
                if key.startswith('folder:'): create(key)
        if self.import_objects:
            self.counts.update(placed_objects=0, placed_placeholders=0, object_sources=len(assets), object_templates=0)
            for i, row in enumerate(content['placements']):
                yield f"Placed objects: {i + 1}/{len(content['placements'])}: {row['name']}"
                if row['position'] is None:
                    continue
                folder = self.content_groups.get(f"folder:{row['folder']}")
                category_key = f"objects:{row['folder']}:{row['category']}"
                if category_key not in self.content_groups:
                    self.content_groups[category_key] = self.collection(row['category'].title(), folder or self.content_collection('Objects'))
                collection = self.content_groups[category_key]
                key = (row['source_tag'], row['variant'])
                asset = assets.get(row['source_tag'], {})
                row['diagnostics'].extend(asset.get('diagnostics', []))
                if key in self.templates:
                    self.profile.counts['object_template_cache_hits'] += 1
                else:
                    self.profile.counts['object_template_cache_misses'] += 1
                    yield from self.object_template(key, assets, set(), row['diagnostics'])
                if row.get('stored_pose'):
                    from .scenario_poses import validate_stored_pose
                    row['pose_status'] = validate_stored_pose(row['stored_pose'], self.source_payloads.get(row['source_tag']))
                    if row['pose_status']['status'] != 'empty':
                        row['diagnostics'].append(row['pose_status']['reason'])
                        self.profile.counts['stored_pose_fallback'] += 1
                with self.profile.span('placement instancing and semantic markers'):
                    self.profile.counts['placements'] += 1
                    ob = self.object(row['name'], None, collection, 'placed_object', row['address'])
                    ob.matrix_world = self.content_transform(row['position'], row['rotation'], row['scale'])
                    template = self.templates[key]
                    if template:
                        ob.instance_type = 'COLLECTION'
                        ob.instance_collection = template
                        ob.hide_render = False
                    else:
                        semantic = asset.get('status') == 'semantic'
                        ob.empty_display_type = 'SPHERE' if row['category'] == 'sound scenery' else 'ARROWS'
                        if semantic:
                            ob['h3_semantic_source'] = self.semantic_sources[row['source_tag']]
                            ob['h3_source_role'] = 'semantic_reference'
                            self.profile.counts['semantic_references'] += 1
                        ob.empty_display_size = 10. * self.scale
                        ob.show_in_front = True
                        ob.color = (1., .15, .55, 1.)
                        self.counts['placed_placeholders'] += 1
                    ob['h3_source_tag'] = row['source_tag'] or ''
                    ob['h3_source_variant'] = row['variant']
                    ob['h3_palette_index'] = row['palette_index']
                    ob['h3_source_placement'] = json.dumps(row)
                    self.counts['placed_objects'] += 1
        if self.import_content:
            self.counts['content_overlays'] = 0
            for i, row in enumerate(content['overlays']):
                self.content_overlay(row)
                self.counts['content_overlays'] += 1
                if i % 32 == 0: yield f"Authored content overlays: {i + 1}/{len(content['overlays'])}"
        for row in content['placements']:
            for reason in row['diagnostics']:
                content['diagnostics'].append(dict(address=row['address'], reason=reason))
        content['diagnostic_summary'] = summarize(content['diagnostics'])
        for message in messages(content['diagnostic_summary']):
            self.warnings.append(message)
            print(message, flush=True)
        self.root['h3_content_report'] = self.text('H3 scenario content report', content).name

    @measured('authored content overlay creation')
    def content_overlay(self, row):
        collection = self.content_collection(row['parent'])
        data = None
        points = []
        edges = []
        if row['kind'] == 'trigger volumes':
            forward, up = Vector(row['forward']), Vector(row['up'])
            left = up.cross(forward)
            extent = row['extents']
            origin = Vector(row['position'])
            points = [origin + forward * x * extent[0] + left * y * extent[1] + up * z * extent[2]
                      for z in (0,1) for y in (0,1) for x in (0,1)]
            edges = [(i, i ^ bit) for i in range(8) for bit in (1,2,4) if i < (i ^ bit)]
        elif 'end' in row:
            points = [row['position'], row['end']]
            edges = [(0,1)]
        if points:
            data = self.remember(bpy.data.curves, bpy.data.curves.new(row['name'], 'CURVE'))
            data.dimensions = '3D'
            for edge in edges:
                spline = data.splines.new('POLY'); spline.points.add(1)
                for p, index in zip(spline.points, edge):
                    p.co = (*import_transform.position(points[index], scene_nwo=self.context.scene.nwo), 1.)
        ob = self.object(row['name'], data, collection, row['kind'], row['address'])
        if data is None:
            ob.matrix_world = self.content_transform(row['position'], row.get('rotation', (0.,0.,0.)))
            if row.get('frame_matrix'):
                frame = Matrix(row['frame_matrix'])
                frame.translation *= 100. * self.scale
                local = self.content_transform(row['source_position'], row.get('rotation', (0.,0.,0.)))
                ob.matrix_world = self.rotation @ frame @ self.rotation.inverted() @ local
            ob.empty_display_type = 'ARROWS'
            ob.empty_display_size = 8. * self.scale
        ob['h3_source_content'] = json.dumps(row)
        ob.show_in_front = True
        ob.color = (.65, .3, 1., 1.) if row['kind'] == 'trigger volumes' else (.2, 1., .45, 1.)
