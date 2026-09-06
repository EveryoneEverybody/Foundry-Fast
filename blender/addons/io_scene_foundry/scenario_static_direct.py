"""Direct construction for rigid scenario references.

Childless rigid render models bypass Blender armature construction.
Skinned meshes, render-model instances, permutation clones, scenario poses,
and variant children retain the normal reference path.
"""
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import utils
from .managed_blam import import_transform
from .managed_blam.connected_geometry import CompressionBounds, Material, Mesh, Node, Region
from .tools import importer as backend


class DirectStaticUnsupported(ValueError):
    pass


def _read_nodes(render_model):
    nodes = []
    by_name = {}
    for element in render_model.block_nodes.Elements:
        node = Node(element.SelectField("name").GetStringData())
        node.index = element.ElementIndex
        translation = element.SelectField("default translation").Data
        node.translation = Vector(tuple(translation)) * 100
        rotation = element.SelectField("default rotation").Data
        node.rotation = Quaternion((rotation[3], rotation[0], rotation[1], rotation[2]))
        parent_index = element.SelectField("parent node").Value
        if parent_index > -1:
            node.parent_name = render_model.block_nodes.Elements[parent_index].SelectField("name").GetStringData()
        nodes.append(node)
        by_name[node.name] = node

    for node in nodes:
        if node.parent_name:
            node.parent = by_name.get(node.parent_name)
            if node.parent is None:
                raise DirectStaticUnsupported(f"missing render node parent {node.parent_name}")
    return nodes


def _node_world_matrices(nodes, scene_nwo):
    """Match RenderArmature rest matrices without allocating an armature datablock."""
    matrices = {}
    for node in nodes:
        local = Matrix.Translation(node.translation) @ node.rotation.to_matrix().to_4x4()
        local = import_transform.armature_bone_matrix(local, scene_nwo, root=node.parent is None)
        if node.parent is None:
            world = local
        else:
            parent = matrices.get(node.parent.index)
            if parent is None:
                raise DirectStaticUnsupported(f"render node {node.name} appears before its parent")
            world = parent @ local
        matrices[node.index] = world
    return matrices


def _allowed_pair(allowed, region, permutation):
    return not allowed or (region, permutation) in allowed


def _rigid_selection(render_model, allowed_region_permutations):
    """Reject unsupported definitions before allocating materials or meshes."""
    if not render_model.block_compression_info.Elements.Count:
        raise DirectStaticUnsupported("render model has no compression info")

    regions = [Region(element) for element in render_model.block_regions.Elements]
    allowed = set(allowed_region_permutations or ())
    instance_placements = render_model.tag.SelectField("Block:instance placements")
    instance_mesh_index = render_model.tag.SelectField("LongBlockIndex:instance mesh index").Value
    if instance_mesh_index > -1 and instance_placements.Elements.Count:
        raise DirectStaticUnsupported("render-model instance geometry needs the live reference path")

    selected = []
    mesh_count = render_model.block_meshes.Elements.Count
    node_count = render_model.block_nodes.Elements.Count
    for region in regions:
        for permutation in region.permutations:
            if not _allowed_pair(allowed, region.name, permutation.name):
                continue
            if permutation.mesh_index < 0:
                continue
            if permutation.clone_name:
                raise DirectStaticUnsupported("permutation material clones need the live reference path")
            for offset in range(permutation.mesh_count):
                index = permutation.mesh_index + offset
                if not 0 <= index < mesh_count:
                    raise DirectStaticUnsupported(f"invalid render mesh index {index}")
                element = render_model.block_meshes.Elements[index]
                node_index = element.SelectField("rigid node index").Data
                if node_index < 0:
                    raise DirectStaticUnsupported("skinned render geometry needs the live reference path")
                if node_index >= node_count:
                    raise DirectStaticUnsupported(f"invalid rigid node index {node_index}")
                selected.append((region, permutation, index))
    if not selected:
        raise DirectStaticUnsupported("selected render model has no rigid geometry")
    return selected


def build_rigid_render(render_model, collection, allowed_region_permutations, importer):
    """Build selected rigid render geometry directly into Blender without a rig."""
    selected = _rigid_selection(render_model, allowed_region_permutations)
    nodes = _read_nodes(render_model)
    node_matrices = _node_world_matrices(nodes, importer.scene_nwo)
    bounds = CompressionBounds(render_model.block_compression_info.Elements[0])
    game_render_model = render_model._GameRenderModel()
    materials = [Material(element) for element in render_model.block_materials.Elements]
    materials_by_index = {material.index: material for material in materials}
    mesh_node_map = render_model.tag.SelectField("Struct:render geometry[0]/Block:per mesh node map")

    objects = []
    for region, permutation, index in selected:
        mesh = Mesh(
            render_model.block_meshes.Elements[index], bounds, permutation,
            materials_by_index, mesh_node_map,
            from_vert_normals=importer.from_vert_normals,
            tag_path=render_model.tag_path.RelativePathWithExtension,
        )
        node_matrix = node_matrices[mesh.rigid_node_index]
        created = mesh.create(game_render_model, render_model.block_per_mesh_temporary, nodes, None)
        for ob in created:
            ob.matrix_world = node_matrix.copy()
            ob.nwo.export_this = False
            utils.set_region(ob, region.name, utils.SetType.MODEL)
            utils.set_permutation(ob, permutation.name, utils.SetType.MODEL)
            collection.objects.link(ob)
        objects.extend(created)

    if not objects:
        raise DirectStaticUnsupported("selected render model has no rigid geometry")
    return objects


def _first_model_variant(model):
    if model.block_variants.Elements.Count:
        return model.block_variants.Elements[0].Fields[0].GetStringData()
    return ""


def try_build(importer, game_object, pose, session):
    """Return (collection, reason). Collection is None when the live path is required."""
    if pose:
        return None, "scenario skeleton pose requires the live reference path"
    if importer.tag_import_attachments:
        return None, "object tag attachments require the live reference path"

    requested_tag = game_object.nwo.marker_game_instance_tag_name
    requested_variant = game_object.nwo.marker_game_instance_tag_variant_name
    file = str(Path(utils.get_tags_path(), requested_tag))
    root = None
    try:
        with utils.TagImportMover(importer.tags_dir, file) as mover:
            with backend.ObjectTag(path=mover.tag_path, raise_on_error=False) as obj:
                if requested_variant.strip():
                    variant = requested_variant
                elif obj.default_variant.GetStringData():
                    variant = obj.default_variant.GetStringData()
                else:
                    variant = ""

                model_path = obj.get_model_tag_path_full()
                if not model_path or not Path(model_path).exists():
                    return None, "object has no readable model tag"
                change_colors = obj.get_change_colors(variant)

                with utils.TagImportMover(importer.tags_dir, model_path) as model_mover:
                    with backend.ModelTag(path=model_mover.tag_path, raise_on_error=False) as model:
                        if not model.valid:
                            return None, "model tag is invalid"
                        source_root = mover.potential_source_tag_dir if model_mover.needs_to_move else importer.tags_dir
                        render, _, _, _ = model.get_model_paths(optional_tag_root=source_root)
                        if not render:
                            return None, "model has no render model"
                        if not variant:
                            variant = _first_model_variant(model)
                        allowed = model.get_variant_regions_and_permutations(variant, importer.tag_state)
                        if importer.import_variant_children and variant:
                            children = [child for child in model.get_variant_children(variant) if child.child_object is not None]
                            if children:
                                return None, "variant child objects require the live attachment path"

                        name = model.tag_path.ShortName
                        root = bpy.data.collections.new(f"{name} [{variant}]" if variant else name)
                        importer.scene_collection.children.link(root)
                        render_collection = bpy.data.collections.new(f"{Path(str(render)).with_suffix('').name}_render")
                        root.children.link(render_collection)

                        with utils.TagImportMover(importer.tags_dir, render) as render_mover:
                            with backend.RenderModelTag(path=render_mover.tag_path) as render_model:
                                with session.time('direct rigid geometry'):
                                    render_objects = build_rigid_render(render_model, render_collection, allowed, importer)

                        functions = obj.functions_to_blender()
                        for ob in render_objects:
                            if ob.type != 'MESH':
                                continue
                            if change_colors is not None:
                                importer._apply_change_color_properties(ob, change_colors)
                            importer.obs_for_props[ob] = functions
                            ob['reference_source_tag'] = requested_tag
                            ob['reference_requested_variant'] = requested_variant
                            ob['reference_resolved_variant'] = variant
                            ob.nwo.export_this = False

                        root['reference_variant'] = variant
                        root['reference_state'] = importer.tag_state
                        root['reference_direct_static'] = True
                        return root, None
    except DirectStaticUnsupported as error:
        if root is not None and root.name in bpy.data.collections:
            backend.remove_collection_hierarchy(root)
        return None, str(error)
    except Exception:
        if root is not None and root.name in bpy.data.collections:
            backend.remove_collection_hierarchy(root)
        raise
