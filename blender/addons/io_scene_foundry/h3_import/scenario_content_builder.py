"""Organize source content and instance the existing H3 object builder's output."""
import json
import re
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

from ..managed_blam import import_transform
from . import scenario_content, scenario_objects
from .builder import BuildSession
from .core import load_payload


class ContentBuilder:
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
            assets = self.object_assets
            if assets is None and self.tags_root and self.object_helper:
                assets = yield from scenario_objects.extract(content, self.tags_root, self.directory,
                    self.object_helper, self.preview_materials)
            assets = assets or {}
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
                if key not in self.templates:
                    template = None
                    if asset.get('status') == 'extracted':
                        session = None
                        try:
                            payload = load_payload(asset['asset'])
                            if payload['source_tag'] != row['source_tag']:
                                raise ValueError('Placed extraction source identity mismatch')
                            session = BuildSession(self.context, payload, asset['asset'], True,
                                self.preview_materials, self.flip_normal_green, source_axes=True, variant=row['variant'])
                            for phase in session.build():
                                yield f"Object template {len(self.templates) + 1}: {row['name']}: {phase}"
                            template = session.root
                            # Templates must be linked while the normal builder operates
                            # on armatures. Only collection instances remain in the scene.
                            self.context.scene.collection.children.unlink(template)
                            for ob in template.all_objects:
                                ob.nwo.export_this = False
                                ob['h3_reference_only'] = True
                            def exclude(c):
                                c.nwo.type = 'exclude'
                                for child in c.children: exclude(child)
                            exclude(template)
                            self.created.extend(session.created)
                            session.created.clear()
                            row['diagnostics'].extend(session.warnings)
                            self.counts['object_templates'] += 1
                        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                            if session: session.rollback()
                            row['diagnostics'].append(f'Object construction failed: {error}')
                        finally:
                            # Includes cancellation while the nested builder is yielded.
                            if session and session.created:
                                session.rollback()
                    elif row['source_tag']:
                        row['diagnostics'].append('Source object geometry unavailable; placement shown as a reference marker')
                    self.templates[key] = template
                ob = self.object(row['name'], None, collection, 'placed_object', row['address'])
                ob.matrix_world = self.content_transform(row['position'], row['rotation'], row['scale'])
                template = self.templates[key]
                if template:
                    ob.instance_type = 'COLLECTION'
                    ob.instance_collection = template
                    ob.hide_render = False
                else:
                    ob.empty_display_type = 'ARROWS'
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
        for row in content['diagnostics']:
            message = f"H3 scenario {row['address']}: {row['reason']}"
            self.warnings.append(message)
            print(message, flush=True)
        self.root['h3_content_report'] = self.text('H3 scenario content report', content).name

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
            ob.empty_display_type = 'ARROWS'
            ob.empty_display_size = 8. * self.scale
        ob['h3_source_content'] = json.dumps(row)
        ob.show_in_front = True
        ob.color = (.65, .3, 1., 1.) if row['kind'] == 'trigger volumes' else (.2, 1., .45, 1.)
