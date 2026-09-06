"""Construct Foundry objects from a validated, read-only H3 extraction."""
from collections import defaultdict
import json
from pathlib import Path
import bpy
import bmesh
from mathutils import Matrix, Quaternion, Vector
from .. import utils
from ..managed_blam import import_transform
from .core import compact_mesh, groups, shader_candidates
from .volume_display import configure_material, configure_object


class BuildSession:
    def __init__(self, context, payload, source_path, reference_only=True, preview_materials=False, flip_normal_green=True, *, source_axes=False, variant=None):
        self.context = context
        self.payload = payload
        self.source_path = str(source_path)
        self.reference_only = reference_only
        self.settings = utils.get_scene_props()
        self.scale = import_transform.scale_factor(self.settings)
        self.rotation = import_transform.rotation_matrix(self.settings)
        if source_axes:
            self.rotation = Matrix.Identity(4)
        self.variant = variant
        self.variant_regions = None
        self.created = []
        self.warnings = list(payload.get("warnings", []))
        self.armature = None
        self.preview_materials = preview_materials
        self.flip_normal_green = flip_normal_green
        self.render_materials = []
        self.physics_material = None
        if variant is not None:
            from .scenario_objects import variant_regions
            self.variant_regions, warnings = variant_regions(payload, variant)
            self.warnings.extend(warnings)

    def remember(self, store, value):
        self.created.append((store, value))
        return value

    def collection(self, name, parent, excluded=False):
        collection = self.remember(bpy.data.collections, bpy.data.collections.new(name))
        parent.children.link(collection)
        if excluded:
            collection.nwo.type = 'exclude'
        return collection

    def position(self, position):
        return self.rotation.to_3x3() @ (Vector(position) * self.scale)

    def matrix(self, data, rotate=True):
        matrix = Matrix.LocRotScale(Vector(data["position"]) * self.scale,
                                    Quaternion(data["rotation"]).normalized(), Vector((1, 1, 1)))
        return self.rotation @ matrix if rotate else matrix

    def object(self, name, data, collection):
        ob = self.remember(bpy.data.objects, bpy.data.objects.new(name, data))
        collection.objects.link(ob)
        return ob

    def build_armature(self, collection):
        nodes = self.payload["render"]["nodes"]
        if not nodes:
            return
        data = self.remember(bpy.data.armatures, bpy.data.armatures.new(self.payload["name"]))
        armature = self.object(self.payload["name"], data, collection)
        self.armature = armature
        for selected in self.context.selected_objects:
            selected.select_set(False)
        self.context.view_layer.objects.active = armature
        armature.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            bones = []
            for node in nodes:
                bone = data.edit_bones.new(node["name"])
                if bone.name != node["name"]:
                    raise ValueError(f"Blender changed source bone name: {node['name']}")
                bone.head = (0, 0, 0)
                bone.tail = (0, 5 * self.scale, 0)
                bones.append(bone)
            for node, bone in zip(nodes, bones):
                if node["parent"] != -1:
                    bone.parent = bones[node["parent"]]
            for node, bone in zip(nodes, bones):
                bone.matrix = self.matrix(node)
                bone.use_deform = True
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')
        armature.show_in_front = True
        # Foreign paths must never become Reach node-order or cinematic references.
        armature["h3_source_node_order"] = json.dumps([n["name"] for n in nodes])
        armature["h3_source_render_model"] = self.payload.get("dependencies", {}).get("render_model", "")
        self.context.view_layer.update()

    def parent_rigid(self, ob, node, matrix):
        if self.armature is not None and node is not None:
            ob.parent = self.armature
            ob.parent_type = 'BONE'
            ob.parent_bone = node
            self.context.view_layer.update()
        ob.matrix_world = matrix

    def materials(self, mesh, role):
        materials = []
        for slot, source in enumerate(mesh["materials"]):
            material = self.remember(bpy.data.materials, bpy.data.materials.new(f"H3 {source['name']}"))
            material["h3_source_name"] = source["name"]
            material["h3_source_label"] = source["label"]
            material["h3_source_slot"] = slot
            material["h3_source_object"] = self.payload["source_tag"]
            if role == "render":
                candidates = shader_candidates(source["name"], self.payload.get("shader_paths", []))
                material["h3_shader_candidates"] = json.dumps(candidates)
                if len(candidates) == 1:
                    material["h3_source_shader"] = candidates[0]
                elif len(candidates) > 1:
                    self.warnings.append(f"Ambiguous shader for material {source['name']}: {candidates}")
            if role == "render":
                self.render_materials.append(material)
            if role == "collision":
                configure_material(material, "collision")
            materials.append(material)
        return materials

    def build_mesh(self, source, key, triangles, materials, collection, role):
        region, permutation, lod, rigid_index, placement = key
        vertices, faces = compact_mesh(source, triangles)
        name = f"{role}:{region}:{permutation}" + (f":{lod}" if lod else "")
        if placement:
            name += ":" + placement
        mesh = self.remember(bpy.data.meshes, bpy.data.meshes.new(name))
        mesh.from_pydata([self.position(v["position"]) for v in vertices], [], faces)
        mesh.update()
        ob = self.object(name, mesh, collection)
        mesh.nwo.mesh_type = f"_connected_geometry_mesh_type_{'collision' if role == 'collision' else 'default'}"
        utils.set_region(ob, region, utils.SetType.MODEL)
        utils.set_permutation(ob, permutation, utils.SetType.MODEL)
        ob["h3_source_lod"] = lod
        if placement:
            ob["h3_source_instance_label"] = placement
            self.warnings.append(f"Instance {placement} uses a provisional default region/permutation. The source placement name is retained; its variant mapping is not reconstructed.")
        if lod:
            self.warnings.append(f"LOD {lod} on {name} is retained as metadata, not translated to a Reach LOD setting")
        material_ids = list(dict.fromkeys(t["material"] for t in triangles))
        remap = {old: new for new, old in enumerate(material_ids)}
        for i in material_ids:
            mesh.materials.append(materials[i])
        mesh.polygons.foreach_set("material_index", [remap[t["material"]] for t in triangles])
        mesh.polygons.foreach_set("use_smooth", [True] * len(faces))
        normals = [self.rotation.to_3x3() @ Vector(v["normal"]) for v in vertices]
        mesh.normals_split_custom_set_from_vertices(normals)
        uv_count = max((len(v["uvs"]) for v in vertices), default=0)
        if uv_count > 8:
            raise ValueError("More than eight source UV channels")
        for uv_index in range(uv_count):
            layer = mesh.uv_layers.new(name="UVMap" if uv_index == 0 else f"UVMap.{uv_index:03d}")
            values = []
            for loop in mesh.loops:
                uvs = vertices[loop.vertex_index]["uvs"]
                values.extend(uvs[uv_index] if uv_index < len(uvs) else (0.0, 0.0))
            layer.data.foreach_set("uv", values)
        if any(v.get("color") is not None for v in vertices):
            colors = mesh.color_attributes.new(name="Color", type='FLOAT_COLOR', domain='CORNER')
            values = []
            for loop in mesh.loops:
                values.extend([*(vertices[loop.vertex_index].get("color") or (0, 0, 0)), 1])
            colors.data.foreach_set("color", values)
        if role == "collision":
            bone = source["nodes"][rigid_index]["name"] if rigid_index != -1 else None
            self.parent_rigid(ob, bone, Matrix.Identity(4))
            configure_object(ob, "collision")
            ob.hide_render = True
        elif self.armature is not None:
            ob.parent = self.armature
            batches = defaultdict(list)
            for i, vertex in enumerate(vertices):
                for bone, weight in vertex["weights"]:
                    if weight > 0:
                        batches[(source["nodes"][bone]["name"], weight)].append(i)
            vertex_groups = {}
            for (name, weight), indices in batches.items():
                group = vertex_groups.get(name)
                if group is None:
                    group = ob.vertex_groups.new(name=name)
                    vertex_groups[name] = group
                group.add(indices, weight, 'REPLACE')
            modifier = ob.modifiers.new("H3 skeleton", 'ARMATURE')
            modifier.object = self.armature
        return ob

    def build_marker(self, marker, collection):
        ob = self.object(marker["name"], None, collection)
        ob.empty_display_type = 'ARROWS'
        ob.empty_display_size = max(marker["radius"], 1.0) * self.scale
        ob.nwo.marker_type = '_connected_geometry_marker_type_model'
        ob["h3_source_marker"] = marker["name"]
        node = marker["node"]
        if self.armature is not None and node != -1:
            bone = self.payload["render"]["nodes"][node]["name"]
            matrix = self.armature.data.bones[bone].matrix_local @ self.matrix(marker, rotate=False)
            matrix = import_transform.keep_marker_axis(matrix, self.settings)
            self.parent_rigid(ob, bone, matrix)
        else:
            ob.matrix_world = import_transform.keep_marker_axis(self.matrix(marker), self.settings)

    def build_physics_reference(self, shape, collection):
        mesh = self.remember(bpy.data.meshes, bpy.data.meshes.new(shape["name"]))
        bm = bmesh.new()
        try:
            if shape["kind"] == 'sphere':
                bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=shape["radius"] * self.scale)
            elif shape["kind"] == 'box':
                bmesh.ops.create_cube(bm, size=1.0)
                dimensions = Vector(shape["size"]) * self.scale
                for vertex in bm.verts:
                    for i in range(3):
                        vertex.co[i] *= dimensions[i]
            else:
                for point in shape["vertices"]:
                    bm.verts.new(Vector(point) * self.scale)
                bmesh.ops.convex_hull(bm, input=list(bm.verts))
                for vertex in list(bm.verts):
                    if not vertex.link_faces:
                        bm.verts.remove(vertex)
            if not bm.faces:
                raise ValueError(f"Empty physics reference shape: {shape['name']}")
            bm.to_mesh(mesh)
        finally:
            bm.free()
        ob = self.object("physics reference:" + shape["name"], mesh, collection)
        ob["h3_physics_source"] = json.dumps(shape)
        if self.physics_material is None:
            self.physics_material = self.remember(bpy.data.materials, bpy.data.materials.new("H3 Physics Reference"))
            configure_material(self.physics_material, "physics")
        mesh.materials.append(self.physics_material)
        configure_object(ob, "physics")
        ob.hide_render = True
        node = shape["node"]
        bone = self.payload["physics"]["nodes"][node]["name"] if node != -1 else None
        if bone is not None and self.armature is not None:
            matrix = self.armature.data.bones[bone].matrix_local @ self.matrix(shape, rotate=False)
        else:
            matrix = self.matrix(shape)
        self.parent_rigid(ob, bone, matrix)

    def build(self):
        root = self.collection("H3 " + self.payload["name"], self.context.scene.collection, self.reference_only)
        self.root = root
        if self.variant is not None:
            root['h3_requested_variant'] = self.variant
            root['h3_source_variants'] = json.dumps(self.payload.get('variants', []))
        root["h3_source_tag"] = self.payload["source_tag"]
        root["h3_extraction_file"] = self.source_path
        root["h3_dependencies"] = json.dumps(self.payload.get("dependencies", {}))
        self.build_armature(root)
        yield "Skeleton"
        for role in ("render", "collision"):
            source = self.payload.get(role)
            if source is None:
                continue
            collection = self.collection(role.title(), root)
            materials = self.materials(source, role)
            for key, triangles in groups(source, collision=role == 'collision').items():
                if self.variant_regions is not None and key[0] in self.variant_regions and key[1] not in self.variant_regions[key[0]]:
                    continue
                self.build_mesh(source, key, triangles, materials, collection, role)
                yield f"{role}: {key[0]} / {key[1]}"
        markers = self.collection("Markers", root)
        for marker in self.payload["render"]["markers"]:
            self.build_marker(marker, markers)
            yield "Marker: " + marker["name"]
        if self.payload.get("physics"):
            physics = self.collection("Physics References - Excluded", root, True)
            for shape in self.payload["physics"]["shapes"]:
                self.build_physics_reference(shape, physics)
                yield "Physics reference: " + shape["name"]
        if self.preview_materials:
            yield from self.build_material_previews(root)
        else:
            self.warnings.append("Materials are placeholders. Halo 3 shader paths are stored as metadata only. Assign valid Reach shader paths before an export test.")
        if self.reference_only:
            self.warnings.append("Reference Only is enabled. The H3 root collection is excluded from Foundry export.")
        report = self.remember(bpy.data.texts, bpy.data.texts.new("H3 import - " + self.payload["name"]))
        report.write("Halo 3 object import\n\nSource: " + self.payload["source_tag"] +
                     "\nExtraction: " + self.source_path + "\n\n" + "\n".join(self.warnings))
        root["h3_import_report"] = report.name
        for warning in self.warnings:
            utils.print_warning(warning)
        if self.armature is not None:
            for ob in self.context.selected_objects:
                ob.select_set(False)
            self.armature.select_set(True)
            self.context.view_layer.objects.active = self.armature
        self.context.view_layer.update()
        yield "Complete"

    def build_material_previews(self, root):
        from .materials import load_manifest
        from .material_builder import PreviewBuilder
        path = Path(self.source_path).parent / 'shader_manifest.json'
        try:
            manifest = load_manifest(path, self.payload['source_tag'])
        except (OSError, ValueError, TypeError) as exc:
            self.warnings.append(f"H3 material metadata unavailable: {exc}. Geometry retained with placeholders.")
            return
        source = self.remember(bpy.data.texts, bpy.data.texts.new("H3 shader source - " + self.payload['name']))
        source.write(json.dumps(manifest, indent=2))
        root['h3_shader_manifest'] = source.name
        builder = PreviewBuilder(manifest, path.parent, self.remember, self.flip_normal_green)
        for i, material in enumerate(self.render_materials):
            material['h3_shader_manifest'] = source.name
            builder.build(material)
            yield f"Material preview: {i + 1} / {len(self.render_materials)}"
        report = self.remember(bpy.data.texts, bpy.data.texts.new("H3 material report - " + self.payload['name']))
        report.write(json.dumps(builder.results, indent=2))
        root['h3_material_report'] = report.name
        built = sum(r['status'] == 'approximate_preview' for r in builder.results)
        print(f"[Foundry perf] H3 materials: {built} previews, {len(builder.results) - built} placeholders, {len(builder.images)} packed images")
        self.warnings.append("Blender material previews are approximations. Reach shader paths remain unassigned; no Reach shader tags were generated. See the H3 material report for unsupported features.")

    def rollback(self):
        if self.context.object is not None and self.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for store, value in reversed(self.created):
            try:
                store.remove(value, do_unlink=True)
            except (ReferenceError, RuntimeError, TypeError):
                try:
                    store.remove(value)
                except (ReferenceError, RuntimeError):
                    pass
        self.created.clear()
