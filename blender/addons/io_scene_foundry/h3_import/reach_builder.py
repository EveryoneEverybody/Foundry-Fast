"""Build native Foundry Reach nodes without writing destination tags."""
import json
import bpy
from .. import utils
from .materials import _object_pairs, validate_manifest
from .reach_materials import (CATEGORIES, GROUP_NAME, normalized,
                             parameter_bindings, stage_name, staged_image_key,
                             staged_image_name, validate_shader)


def socket_schema(group):
    return [{'name': s.name, 'type': s.type, 'visible': s.is_icon_visible}
            for s in group.inputs if s.type != 'MENU']


class ReachStager:
    def __init__(self, resource_loader=None, alias_loader=None):
        self.resource_loader = resource_loader or utils.add_node_from_resources
        self.alias_loader = alias_loader or read_destination_aliases
        self.images = {}
        self.created = []
        self.assignments = []
        self.source_users = []
        self.results = []
        self.option_cache = {}
        self.manifests = {}

    def remember(self, store, value):
        self.created.append((store, value))
        return value

    def source_record(self, material):
        text_name = material.get('h3_shader_manifest', '')
        if text_name not in self.manifests:
            text = bpy.data.texts.get(text_name)
            if text is None:
                raise ValueError('Source manifest is missing; re-import with Material Previews enabled')
            if len(text.as_string()) > 64 * 1024 * 1024:
                raise ValueError('Source manifest exceeds 64 MiB')
            manifest = json.loads(text.as_string(), object_pairs_hook=_object_pairs)
            validate_manifest(manifest, material.get('h3_source_object', ''))
            self.manifests[text_name] = manifest
        manifest = self.manifests[text_name]
        if manifest['source_tag'] != material.get('h3_source_object'):
            raise ValueError('Source manifest belongs to a different H3 import')
        source = material.get('h3_source_shader', '')
        record = manifest['shaders'].get(source)
        if record is None:
            raise ValueError('No unambiguous source shader record')
        return manifest, record

    def image(self, bitmap, parameter, source):
        key = staged_image_key(bitmap, parameter['name'])
        cache_key = (source.get('h3_shader_manifest'), *key)
        if cache_key in self.images:
            return self.images[cache_key]
        candidates = []
        if source.node_tree:
            candidates = [n.image for n in source.node_tree.nodes
                          if n.type == 'TEX_IMAGE' and n.image]
        for other in bpy.data.materials:
            if other == source or other.get('h3_shader_manifest') != source.get('h3_shader_manifest'):
                continue
            if other.node_tree:
                candidates.extend(n.image for n in other.node_tree.nodes
                                  if n.type == 'TEX_IMAGE' and n.image)
        image = next((image for image in candidates
                      if image.get('h3_source_bitmap', '').replace('\\', '/').casefold() == key[0]
                      and image.get('h3_bitmap_index') == key[1]
                      and (image.packed_file is not None or image.has_data)), None)
        if image is None:
            raise ValueError('No loaded source pixels; re-import with Material Previews enabled')
        # Destination export properties must not change an H3 preview image.
        image = self.remember(bpy.data.images, image.copy())
        image.name = staged_image_name(bitmap, parameter['name'])
        if image.colorspace_settings.name != key[2]:
            image.colorspace_settings.name = key[2]
        image.alpha_mode = 'CHANNEL_PACKED'
        image.nwo.filepath = ''
        image.nwo.source_name = ''
        image.nwo.bitmap_type = key[3]
        image.nwo.reexport_tiff = False
        image['h3_reach_staged_image'] = True
        # Image.copy retains packed bytes. Repacking would reopen a deleted extraction path.
        if image.packed_file is None:
            image.pack()
        if image.packed_file is None:
            raise ValueError('Staged image has no packed source data')
        # Clear export identity without requesting an image reload.
        image.filepath_raw = ''
        self.images[cache_key] = image
        return image

    def texture(self, tree, source, manifest, parameter, row, report):
        bitmap = manifest['bitmaps'].get(parameter.get('bitmap'))
        if bitmap is None or not bitmap.get('preview'):
            raise ValueError((bitmap or {}).get('preview_error', 'No decoded 2D bitmap'))
        image = self.image(bitmap, parameter, source)
        tex = tree.nodes.new('ShaderNodeTexImage')
        tex.label = parameter['name']
        tex.image = image
        tex.location = (-260, -row * 300)
        tex.width = 220
        uv = tree.nodes.new('ShaderNodeUVMap')
        uv.uv_map = 'UVMap'
        uv.location = (-760, -row * 300)
        tiling = tree.nodes.new('ShaderNodeGroup')
        tiling.node_tree = self.resource_loader('shared_nodes', 'Texture Tiling')
        if tiling.node_tree is None:
            raise ValueError('Foundry Texture Tiling resource is missing')
        tiling.label = parameter['name'] + ' transform'
        tiling.location = (-520, -row * 300)
        sx, sy, tx, ty = parameter['transform']
        for name, value in (('Scale X', sx), ('Scale Y', sy), ('Scale Multiplier', 1),
                            ('Translate X', tx), ('Translate Y', ty)):
            tiling.inputs[name].default_value = value
        tree.links.new(uv.outputs['UV'], tiling.inputs['Vector'])
        tree.links.new(tiling.outputs[0], tex.inputs['Vector'])
        sampler = parameter.get('sampler', {})
        x, y = sampler.get('address_x', 'wrap'), sampler.get('address_y', 'wrap')
        modes = {'wrap': 'REPEAT', 'clamp': 'EXTEND', 'mirror': 'MIRROR', 'border': 'CLIP'}
        tex.extension = modes.get(x, 'REPEAT') if x == y else 'REPEAT'
        tex.interpolation = 'Closest' if sampler.get('filter') == 'point' else 'Linear'
        if x != y or x not in modes:
            report['diagnostics'].append(f"{parameter['name']}: addressing {x}/{y} uses Repeat in the node preview")
        tex['h3_source_sampler'] = json.dumps(sampler)
        return tex

    def build(self, source):
        report = {'source_material': source.name, 'source_shader': source.get('h3_source_shader'),
                  'status': 'skipped', 'destination_shader': None, 'categories': [],
                  'parameters': [], 'diagnostics': []}
        self.results.append(report)
        checkpoint = len(self.created)
        try:
            manifest, record = self.source_record(source)
            categories, parameters = validate_shader(record)
            material = self.remember(bpy.data.materials, bpy.data.materials.new(stage_name(record['source'])))
            material.use_nodes = True
            material.node_tree.nodes.clear()
            tree = material.node_tree
            group = tree.nodes.new('ShaderNodeGroup')
            group.node_tree = self.resource_loader('reach_nodes', GROUP_NAME)
            if group.node_tree is None:
                raise ValueError('Bundled Foundry Reach shader group is missing')
            group.location = (60, 0)
            group.width = 380
            output = tree.nodes.new('ShaderNodeOutputMaterial')
            output.location = (500, 0)
            tree.links.new(group.outputs[0], output.inputs['Surface'])
            selected = {}
            for name, choice in categories.items():
                option = choice['option']
                target = group.inputs.get(name)
                status = 'unexposed'
                if name in CATEGORIES and target is not None and target.type == 'MENU':
                    previous = target.default_value
                    try:
                        target.default_value = option
                        if normalized(str(target.default_value)) != normalized(option):
                            raise ValueError('Option selection was not accepted')
                        selected[name] = option
                        status = 'name_match'
                    except (ValueError, TypeError):
                        target.default_value = previous
                        status = 'group_default'
                report['categories'].append({'category': name, 'source_option': option, 'status': status,
                                             'node_option': str(target.default_value) if target else None})
                if status != 'name_match':
                    report['diagnostics'].append(f'{name}={option}: {status}; source selection retained in the manifest')
            tree.interface_update(bpy.context)
            aliases, contract_notes = self.alias_loader(selected, self.option_cache)
            report['diagnostics'].extend(contract_notes)
            sockets = socket_schema(group)
            claimed = set()
            row = 0
            for name, parameter in parameters.items():
                item = {'name': name, 'type': parameter['type'], 'origin': parameter.get('origin'),
                        'status': 'unmapped', 'sockets': []}
                report['parameters'].append(item)
                if parameter.get('extern'):
                    item.update(status='runtime_input', extern=parameter['extern'])
                    continue
                bindings = parameter_bindings(parameter, sockets, aliases.get(name, ()))
                if not bindings:
                    continue
                if any(socket in claimed for socket, _ in bindings):
                    item['status'] = 'ambiguous_socket'
                    continue
                try:
                    tex = None
                    if parameter['type'] == 'bitmap':
                        tex = self.texture(tree, source, manifest, parameter, row, report)
                        row += 1
                    for socket_name, channel in bindings:
                        socket = group.inputs[socket_name]
                        if tex is not None:
                            tree.links.new(tex.outputs['Alpha' if channel == 'alpha' else 'Color'], socket)
                        elif channel == 'alpha_value':
                            socket.default_value = parameter['value'][3]
                        elif channel == 'color_value':
                            value = parameter['value']
                            socket.default_value = value[:3] if socket.type == 'VECTOR' else value
                        else:
                            socket.default_value = parameter['value']
                        claimed.add(socket_name)
                        item['sockets'].append(socket_name)
                    item['status'] = 'snapshot' if parameter.get('has_functions') else 'mapped'
                except (ValueError, TypeError, KeyError, RuntimeError) as exc:
                    item.update(status='unavailable', reason=str(exc))
            if not any(p['status'] in {'mapped', 'snapshot'} for p in report['parameters']):
                raise ValueError('No source parameters could be connected to this Reach shader group')
            if selected.get('blend_mode', 'opaque') != 'opaque' or selected.get('alpha_test', 'none') != 'none':
                material.surface_render_method = 'BLENDED'
                sided = group.inputs.get('material is two-sided')
                if sided is not None:
                    sided.default_value = True
                report['diagnostics'].append('Blended/two-sided node preview follows Foundry import defaults, not verified source surface flags')
            for key in ('h3_source_shader', 'h3_source_object', 'h3_source_name', 'h3_shader_manifest'):
                if key in source:
                    material[key] = source[key]
            material['h3_source_material'] = source
            material['h3_reach_staged'] = True
            material.nwo.shader_type = '.shader'
            material.nwo.shader_path = ''
            material.nwo.uses_blender_nodes = True
            report.update(status='native_nodes_staged', material=material.name)
            report['diagnostics'] += [
                'Names and socket types are matched; equivalent HLSL behavior is not asserted',
                'Animated parameters use the extracted snapshot; runtime functions remain in the source manifest',
                'Native Reach nodes consume raw normal textures; the H3 preview green-flip nodes are not copied',
                'Sampler export, complete defaults and reference inheritance are not validated by this staging operation',
                'No Reach shader or bitmap tags were written']
            material['h3_reach_report'] = json.dumps(report)
            return material
        except Exception as exc:
            report['diagnostics'].append(str(exc))
            removed = {value for store, value in self.created[checkpoint:] if store == bpy.data.images}
            self.images = {key: image for key, image in self.images.items() if image not in removed}
            self._remove_created(checkpoint)
            return None

    def apply(self, objects):
        converted = {}
        for ob in objects:
            if ob.type != 'MESH' or ob.library or ob.data.library:
                continue
            for slot in ob.material_slots:
                source = slot.material
                if source is None or source.library or source.get('h3_reach_staged') or not source.get('h3_source_shader'):
                    continue
                if source not in converted:
                    converted[source] = self.build(source)
                material = converted[source]
                if material is None:
                    continue
                if not any(old is source for old, _ in self.source_users):
                    self.source_users.append((source, source.use_fake_user))
                    source.use_fake_user = True
                # Object-linked slots leave shared source meshes and other collections unchanged.
                self.assignments.append((slot, slot.link, source))
                slot.link = 'OBJECT'
                slot.material = material
        return sum(material is not None for material in converted.values())

    def _remove_created(self, start=0):
        for store, value in reversed(self.created[start:]):
            store.remove(value)
        del self.created[start:]

    def rollback(self):
        for slot, link, source in reversed(self.assignments):
            slot.material = source
            slot.link = link
        for source, fake_user in self.source_users:
            source.use_fake_user = fake_user
        self._remove_created()
        self.assignments.clear()
        self.source_users.clear()
        self.images.clear()


def read_destination_aliases(selected, cache):
    """Read UI aliases for selected Reach options without creating missing tags."""
    aliases = {}
    try:
        from ..managed_blam.render_method_definition import RenderMethodDefinitionTag
        from ..managed_blam.render_method_option import RenderMethodOptionTag
        with RenderMethodDefinitionTag(path='shaders/shader.render_method_definition', tag_must_exist=True) as definition:
            for category in definition.block_categories.Elements:
                name = category.Fields[0].GetStringData()
                if name not in selected:
                    continue
                option = next((o for o in category.Fields[1].Elements
                               if o.Fields[0].GetStringData() == selected[name]), None)
                if option is None or option.Fields[1].Path is None:
                    continue
                path = option.Fields[1].Path
                key = path.RelativePathWithExtension
                if key not in cache:
                    with RenderMethodOptionTag(path=path, tag_must_exist=True) as rmop:
                        cache[key] = [(e.Fields[0].GetStringData(), e.Fields[1].GetStringData())
                                      for e in rmop.block_parameters.Elements]
                for parameter, ui_name in cache[key]:
                    if ui_name and ui_name != parameter:
                        aliases.setdefault(parameter, []).append(ui_name)
        return aliases, []
    except Exception as exc:
        return aliases, [f'Reach option UI aliases unavailable: {exc}. Matching exposed socket names only']
