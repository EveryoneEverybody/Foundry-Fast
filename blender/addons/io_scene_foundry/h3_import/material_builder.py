"""Packed Blender previews for decoded H3 object materials."""
import json
import bpy
from .materials import DETAIL_MULTIPLIER, ILLUMINATION_MODES, color_space, image_key, plan, preview_path


class PreviewBuilder:
    def __init__(self, manifest, directory, remember, flip_normal_green=True):
        self.manifest = manifest
        self.directory = directory
        self.remember = remember
        self.flip_normal_green = flip_normal_green
        self.images = {}
        self.results = []

    def build(self, material):
        source = material.get('h3_source_shader')
        record = self.manifest['shaders'].get(source)
        result = {'material': material.name, 'source': source, 'status': 'placeholder', 'diagnostics': []}
        self.results.append(result)
        if record is None:
            result['diagnostics'].append('No unambiguous source shader record')
            return
        try:
            recipe = plan(record)
            nodes = MaterialNodes(self, material, recipe)
            nodes.build()
            result['status'] = 'approximate_preview'
            result['diagnostics'] = list(dict.fromkeys(nodes.diagnostics))
        except Exception as exc:
            result['diagnostics'].append(str(exc))
            # A partial preview must not masquerade as a completed conversion.
            material.use_nodes = False
        material['h3_material_preview'] = result['status']
        material['h3_material_diagnostics'] = json.dumps(result['diagnostics'])
        # Leave nwo.shader_path and uses_blender_nodes untouched.

    def image(self, bitmap, role):
        key = image_key(bitmap, role)
        if key not in self.images:
            path = preview_path(self.directory, bitmap.get('preview'))
            image = self.remember(bpy.data.images, bpy.data.images.load(str(path), check_existing=False))
            image.name = 'H3 ' + bitmap['path'].replace('\\', '/').rsplit('/', 1)[-1] + ' [' + role + ']'
            image.colorspace_settings.name = color_space(bitmap, role)
            image.alpha_mode = 'CHANNEL_PACKED'
            image['h3_source_bitmap'] = bitmap['path']
            image['h3_bitmap_index'] = bitmap['index']
            image['h3_bitmap_curve'] = str(bitmap.get('curve', 'Unknown'))
            image.pack()
            self.images[key] = image
        return self.images[key]


class MaterialNodes:
    def __init__(self, owner, material, recipe):
        self.owner = owner
        self.material = material
        self.p = recipe['parameters']
        self.c = recipe['categories']
        self.albedo = recipe['albedo']
        self.illumination_surface = recipe['illumination_surface']
        self.diagnostics = recipe['diagnostics']
        material.use_nodes = True
        self.tree = material.node_tree
        self.tree.nodes.clear()
        self.textures = {}
        self.used = set()

    def node(self, kind, label):
        node = self.tree.nodes.new(kind)
        node.label = label
        return node

    def feed(self, value, socket):
        if hasattr(value, 'node'):
            self.tree.links.new(value, socket)
        else:
            if isinstance(value, (list, tuple)):
                size = len(socket.default_value)
                value = tuple(value[:size]) + (1.0,) * max(0, size - len(value))
            socket.default_value = value

    def scalar(self, name, fallback):
        p = self.p.get(name, {})
        self.used.add(name)
        if p.get('extern'):
            self.diagnostics.append(f'{name}: runtime extern {p["extern"]} unavailable')
            return fallback
        return p.get('value', fallback)

    def color(self, name, fallback=(1, 1, 1, 1)):
        value = self.scalar(name, list(fallback))
        return tuple(value) if isinstance(value, (list, tuple)) and len(value) == 4 else fallback

    def math(self, operation, a, b, label):
        node = self.node('ShaderNodeMath', label)
        node.operation = operation
        self.feed(a, node.inputs[0]); self.feed(b, node.inputs[1])
        return node.outputs[0]

    def vector(self, operation, a, b, label):
        node = self.node('ShaderNodeVectorMath', label)
        node.operation = operation
        self.feed(a, node.inputs[0]); self.feed(b, node.inputs[1])
        return node.outputs[0]

    def mix(self, factor, a, b, label):
        node = self.node('ShaderNodeMixRGB', label)
        node.blend_type = 'MIX'
        self.feed(factor, node.inputs[0]); self.feed(a, node.inputs[1]); self.feed(b, node.inputs[2])
        return node.outputs[0]

    def texture(self, name, role='color'):
        self.used.add(name)
        key = (name, role)
        if key in self.textures:
            return self.textures[key]
        p = self.p.get(name)
        if p is None:
            return None
        if p.get('extern'):
            self.diagnostics.append(f'{name}: engine texture {p["extern"]} is not an image file')
            return None
        bitmap = self.owner.manifest['bitmaps'].get(p.get('bitmap'))
        if bitmap is None or not bitmap.get('preview'):
            detail = (bitmap or {}).get('preview_error') or (bitmap or {}).get('error', 'No decoded 2D texture')
            self.diagnostics.append(f'{name}: {detail}')
            return None
        try:
            image = self.owner.image(bitmap, role)
        except Exception as exc:
            self.diagnostics.append(f'{name}: {exc}')
            return None
        image_node = self.node('ShaderNodeTexImage', name)
        image_node.image = image
        uv = self.node('ShaderNodeUVMap', name + ' UV')
        uv.uv_map = 'UVMap'
        transform = p.get('transform', [1, 1, 0, 0])
        scale = self.vector('MULTIPLY', uv.outputs['UV'], (transform[0], transform[1], 1), name + ' scale')
        offset = self.vector('ADD', scale, (transform[2], transform[3], 0), name + ' offset')
        self.tree.links.new(offset, image_node.inputs['Vector'])
        sampler = p.get('sampler', {})
        x, y = sampler.get('address_x', 'wrap'), sampler.get('address_y', 'wrap')
        modes = {'wrap': 'REPEAT', 'clamp': 'EXTEND', 'mirror': 'MIRROR', 'border': 'CLIP'}
        if x == y and x in modes:
            image_node.extension = modes[x]
        else:
            image_node.extension = 'REPEAT'
            self.diagnostics.append(f'{name}: sampler {x}/{y} approximated by repeat')
        filter_mode = sampler.get('filter', '')
        image_node.interpolation = 'Closest' if filter_mode == 'point' else 'Linear'
        if filter_mode not in {'point', 'linear', 'bilinear'} or sampler.get('anisotropy', 0):
            self.diagnostics.append(f'{name}: GPU filtering/anisotropy is not reproduced exactly')
        if role == 'color' and str(bitmap.get('curve', '')).lower() not in {'linear', 'srgb'}:
            self.diagnostics.append(f'{name}: bitmap curve {bitmap.get("curve")} approximated with sRGB')
        self.textures[key] = image_node
        return image_node

    def sample(self, name, role='color', fallback=(1, 1, 1)):
        tex = self.texture(name, role)
        return (tex.outputs['Color'], tex.outputs['Alpha']) if tex else (fallback, 1.0)

    def build(self):
        output = self.node('ShaderNodeOutputMaterial', 'Blender preview only')
        surface = self.node('ShaderNodeBsdfPrincipled', 'Approximate H3 surface')
        surface.inputs['Roughness'].default_value = 0.45
        self.tree.links.new(surface.outputs['BSDF'], output.inputs['Surface'])
        tint = self.color('albedo_color')
        if self.albedo == 'constant_color':
            rgb, alpha = tint[:3], tint[3]
        else:
            base, base_alpha = self.sample('base_map')
            rgb, alpha = base, base_alpha
            if self.albedo in {'default', 'detail_blend', 'two_change_color', 'four_change_color'}:
                # The neutral detail texture is the reciprocal of the H3 multiplier.
                detail, detail_alpha = self.sample('detail_map', fallback=(1 / DETAIL_MULTIPLIER,) * 3)
                if self.albedo == 'detail_blend':
                    d2, a2 = self.sample('detail_map2', fallback=(1 / DETAIL_MULTIPLIER,) * 3)
                    detail = self.mix(base_alpha, detail, d2, 'Detail blend')
                    alpha = self.math('ADD', self.math('MULTIPLY', self.math('SUBTRACT', 1, base_alpha, 'Inverse mask'), detail_alpha, 'Detail A alpha'), self.math('MULTIPLY', base_alpha, a2, 'Detail B alpha'), 'Detail alpha')
                else:
                    alpha = self.math('MULTIPLY', base_alpha, detail_alpha, 'Base x detail alpha')
                rgb = self.vector('MULTIPLY', base, self.vector('MULTIPLY', detail, (DETAIL_MULTIPLIER,) * 3, 'H3 detail multiplier'), 'Base x detail')
            if self.albedo == 'default':
                rgb = self.vector('MULTIPLY', rgb, tint[:3], 'Albedo tint')
                alpha = self.math('MULTIPLY', alpha, tint[3], 'Tint alpha')
            elif self.albedo in {'two_change_color', 'four_change_color'}:
                mask = self.texture('change_color_map', 'data')
                if mask:
                    split = self.node('ShaderNodeSeparateColor', 'Change-color channels')
                    split.mode = 'RGB'
                    self.tree.links.new(mask.outputs['Color'], split.inputs['Color'])
                    channels = [split.outputs['Red'], split.outputs['Green'], split.outputs['Blue'], mask.outputs['Alpha']]
                    names = ['primary_change_color', 'secondary_change_color', 'tertiary_change_color', 'quaternary_change_color']
                    for channel, name in list(zip(channels, names))[:2 if self.albedo == 'two_change_color' else 4]:
                        color = self.color(name)
                        mixed = self.mix(channel, (1, 1, 1, 1), color, name)
                        rgb = self.vector('MULTIPLY', rgb, mixed, name + ' mask')
                self.diagnostics.append('Object change colors require manual preview values; model variants are not applied')
        # Alpha is used for cutouts/blending only when the shader opts into it.
        coverage = None
        if self.c.get('alpha_test', 'none') not in {'none', 'off'}:
            test = self.texture('alpha_test_map', 'data')
            if test:
                coverage = self.math('GREATER_THAN', test.outputs['Alpha'], 0.5, 'Alpha-test preview')
                self.feed(coverage, surface.inputs['Alpha'])
            self.diagnostics.append('Alpha test uses a 0.5 cutout; Halo coverage rules are not reproduced')
        blend = self.c.get('blend_mode', 'opaque')
        if blend in {'alpha_blend', 'pre_multiplied_alpha'}:
            if coverage is not None:
                alpha = self.math('MULTIPLY', alpha, coverage, 'Cutout x blend alpha')
            self.feed(alpha, surface.inputs['Alpha'])
            self.diagnostics.append(f'{blend}: Blender alpha preview, not Halo pass compositing')
        elif blend != 'opaque' and self.illumination_surface != 'additive':
            self.diagnostics.append(f'Blend mode {blend} is not reproduced')
        bump = self.c.get('bump_mapping', 'off')
        if bump not in {'off', 'none'}:
            tex = self.texture('bump_map', 'data')
            if tex:
                color = tex.outputs['Color']
                if self.owner.flip_normal_green:
                    split = self.node('ShaderNodeSeparateXYZ', 'Normal channels')
                    self.tree.links.new(color, split.inputs[0])
                    combine = self.node('ShaderNodeCombineXYZ', 'Flip normal green')
                    self.feed(split.outputs['X'], combine.inputs['X'])
                    self.feed(self.math('SUBTRACT', 1, split.outputs['Y'], '1 - normal green'), combine.inputs['Y'])
                    self.feed(split.outputs['Z'], combine.inputs['Z'])
                    color = combine.outputs[0]
                normal = self.node('ShaderNodeNormalMap', 'H3 normal preview')
                normal.space = 'TANGENT'; normal.uv_map = 'UVMap'
                self.feed(color, normal.inputs['Color'])
                self.tree.links.new(normal.outputs['Normal'], surface.inputs['Normal'])
            if bump != 'standard':
                self.diagnostics.append(f'Bump option {bump}: base normal only; detail combination is not reproduced')
        illum = self.c.get('self_illumination', 'none')
        emission, intensity = (0, 0, 0), 0.0
        if illum in ILLUMINATION_MODES:
            color = self.color('self_illum_color')
            intensity = self.scalar('self_illum_intensity', 1.0)
            emission, ea = (rgb, 1.0) if illum == 'from_albedo' else self.sample('self_illum_map', fallback=(0, 0, 0))
            if illum == 'illum_detail':
                # H3 self_illumination.fx returns RGB without alpha masking for this option.
                detail, _ = self.sample('self_illum_detail_map', fallback=(0, 0, 0))
                detail = self.vector('MULTIPLY', detail, (DETAIL_MULTIPLIER,) * 3, 'Illum detail multiplier')
                emission = self.vector('MULTIPLY', emission, detail, 'Self illum x detail')
            emission = self.vector('MULTIPLY', emission, color[:3], 'Emission tint')
            if illum == 'simple_with_alpha_mask':
                intensity = self.math('MULTIPLY', intensity, self.math('MULTIPLY', ea, color[3], 'Emission alpha'), 'Masked emission')
            self.feed(emission, surface.inputs['Emission Color'])
            self.feed(intensity, surface.inputs['Emission Strength'])
            if illum == 'from_albedo':
                rgb = (0, 0, 0)
        elif illum not in {'none', 'off'}:
            self.diagnostics.append(f'Self illumination {illum} is not reproduced')
        self.feed(rgb, surface.inputs['Base Color']) if hasattr(rgb, 'node') else self.feed((*rgb[:3], 1), surface.inputs['Base Color'])
        if self.illumination_surface != 'principled':
            unlit = self.node('ShaderNodeEmission', 'H3 unlit self illumination')
            self.feed(emission, unlit.inputs['Color'])
            self.feed(intensity, unlit.inputs['Strength'])
            result = unlit.outputs['Emission']
            if self.illumination_surface == 'additive':
                transparent = self.node('ShaderNodeBsdfTransparent', 'Additive background transmission')
                transparent.inputs['Color'].default_value = (1, 1, 1, 1)
                add = self.node('ShaderNodeAddShader', 'Additive self illumination preview')
                self.tree.links.new(result, add.inputs[0])
                self.tree.links.new(transparent.outputs['BSDF'], add.inputs[1])
                result = add.outputs[0]
                self.diagnostics.append('Additive self illumination uses emission plus transparency; Halo exposure and pass ordering are not reproduced')
            self.tree.links.new(result, output.inputs['Surface'])
            self.tree.nodes.remove(surface)
            surface = unlit
        # Keep other decoded textures accessible without pretending they affect the preview.
        for name, p in self.p.items():
            if p['type'] == 'bitmap' and name not in self.used:
                role = 'data' if any(s in name for s in ('bump', 'normal', 'mask', 'noise')) else 'color'
                tex = self.texture(name, role)
                if tex:
                    tex.label = name + ' [unconnected source]'
        known = {'albedo', 'bump_mapping', 'alpha_test', 'blend_mode', 'self_illumination'}
        for category, option in self.c.items():
            if category not in known and option not in {'none', 'off'}:
                self.diagnostics.append(f'{category}={option}: retained in metadata, not evaluated by this preview')
        for i, node in enumerate(self.tree.nodes):
            node.location = ((i % 5) * 230, -(i // 5) * 230)
        output.location = (1400, 0); surface.location = (1100, 0)
        if hasattr(self.material, 'surface_render_method'):
            self.material.surface_render_method = 'DITHERED'
