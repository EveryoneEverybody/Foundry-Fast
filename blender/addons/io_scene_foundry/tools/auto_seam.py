from collections import defaultdict
from itertools import product
from math import atan2, floor

import bmesh
import bpy
from mathutils import Matrix, Vector

from ..tools.property_apply import apply_props_material
from ..utils import (
    current_project_valid,
    export_objects_mesh_only,
    get_prefs,
    get_scene_props,
    poll_ui,
    true_permutation,
    true_region,
)


STRUCTURE_MESH_TYPE = "_connected_geometry_mesh_type_structure"
SEAM_MESH_TYPE = "_connected_geometry_mesh_type_seam"
DEFAULT_TOLERANCE = 0.001


class StructureObject:
    __slots__ = ("ob", "mesh", "vertices", "center", "region", "permutation")

    def __init__(self, ob: bpy.types.Object):
        self.ob = ob
        self.mesh = ob.data
        self.vertices = [ob.matrix_world @ vertex.co for vertex in self.mesh.vertices]
        self.center = _object_center(ob)
        self.region = true_region(ob.nwo)
        self.permutation = true_permutation(ob.nwo)


class SeamComponent:
    __slots__ = ("positions", "face_loops", "a_side_point", "b_side_point")

    def __init__(
        self,
        positions: dict[int, Vector],
        face_loops: list[tuple[int, ...]],
        a_side_point: Vector,
        b_side_point: Vector,
    ):
        self.positions = positions
        self.face_loops = face_loops
        self.a_side_point = a_side_point
        self.b_side_point = b_side_point


class NWO_AutoSeam(bpy.types.Operator):
    bl_idname = "nwo.auto_seam"
    bl_label = "Auto Seam"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Generates BSP seams from aligned structure vertices"

    selected_only: bpy.props.BoolProperty(
        name="Selected Objects Only",
        description="Only create seams between selected structure objects",
        default=False,
    )

    tolerance: bpy.props.FloatProperty(
        name="Vertex Tolerance",
        description="Maximum distance between structure vertices for them to be considered aligned",
        default=DEFAULT_TOLERANCE,
        min=0.000001,
        precision=6,
        subtype="DISTANCE",
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and poll_ui(("scenario",)) and len(get_scene_props().regions_table) > 1 and current_project_valid()

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "selected_only")
        layout.prop(self, "tolerance")

    def execute(self, context):
        return self.auto_seam(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def auto_seam(self, context: bpy.types.Context):
        tolerance = max(self.tolerance, 0.000001)
        export_obs = export_objects_mesh_only()
        seam_obs = [ob for ob in export_obs if ob.data.nwo.mesh_type == SEAM_MESH_TYPE]

        if self.selected_only:
            structure_obs = [
                ob for ob in export_obs
                if ob.data.nwo.mesh_type == STRUCTURE_MESH_TYPE and ob in context.selected_objects
            ]
        else:
            structure_obs = [ob for ob in export_obs if ob.data.nwo.mesh_type == STRUCTURE_MESH_TYPE]

        selected_regions = {true_region(structure.nwo) for structure in structure_obs}
        if len(selected_regions) <= 1:
            word = "selection" if self.selected_only else "scene"
            self.report({"WARNING"}, f"Only one structure BSP in {word}")
            return {"CANCELLED"}

        structures = [StructureObject(ob) for ob in structure_obs if ob.data.vertices]
        if len(structures) < 2:
            self.report({"WARNING"}, "At least two structure objects are required")
            return {"CANCELLED"}

        apply_materials = get_prefs().apply_materials
        existing_components, existing_faces = _existing_seam_signatures(seam_obs, tolerance)
        created = 0
        overlapping = 0

        for idx, structure in enumerate(structures):
            for other in structures[idx + 1:]:
                if structure.region == other.region:
                    continue

                for component in _find_seam_components(structure, other, tolerance):
                    component_signature, face_signatures = _component_signatures(component, tolerance)
                    if component_signature in existing_components or (face_signatures and face_signatures.issubset(existing_faces)):
                        overlapping += 1
                        continue

                    seam = _create_seam_object(context, structure, other, component, apply_materials)
                    if seam is None:
                        continue

                    existing_components.add(component_signature)
                    existing_faces.update(face_signatures)
                    created += 1

        if created:
            self.report({"INFO"}, f"Created {created} seam{'s' if created > 1 else ''}")
        elif overlapping:
            self.report({"INFO"}, "Seams already in place")
        else:
            self.report({"WARNING"}, "Failed to create any seams. Ensure structure objects between BSPs have aligned seal vertices")

        return {"FINISHED"}


def _find_seam_components(a: StructureObject, b: StructureObject, tolerance: float) -> list[SeamComponent]:
    positions, a_to_key, b_to_key = _shared_vertex_maps(a, b, tolerance)
    if len(positions) < 3:
        return []

    min_area = tolerance * tolerance
    shared_edges = _shared_edges(a, a_to_key) | _shared_edges(b, b_to_key)
    a_face_loops = _shared_face_loops(a, a_to_key, positions, min_area)
    b_face_loops = _shared_face_loops(b, b_to_key, positions, min_area)
    adjacency = _component_adjacency(positions.keys(), shared_edges, a_face_loops + b_face_loops)
    components = _connected_components(positions.keys(), adjacency)

    seam_components = []
    for component_keys in components:
        if len(component_keys) < 3:
            continue

        face_loops = [loop for loop in a_face_loops if set(loop).issubset(component_keys)]
        if not face_loops:
            face_loops = [loop for loop in b_face_loops if set(loop).issubset(component_keys)]
        if not face_loops:
            component_edges = {edge for edge in shared_edges if edge[0] in component_keys and edge[1] in component_keys}
            face_loops = _fill_component_faces(component_keys, component_edges, positions, min_area, tolerance)

        face_loops = _dedupe_face_loops(face_loops, positions, min_area)
        if not face_loops:
            continue

        used_keys = {key for loop in face_loops for key in loop}
        component_positions = {key: positions[key] for key in used_keys}
        seam_components.append(
            SeamComponent(
                component_positions,
                face_loops,
                _component_side_point(a, a_to_key, used_keys, component_positions),
                _component_side_point(b, b_to_key, used_keys, component_positions),
            )
        )

    return seam_components


def _shared_vertex_maps(a: StructureObject, b: StructureObject, tolerance: float):
    b_grid = _position_grid(enumerate(b.vertices), tolerance)
    shared_positions = {}
    shared_grid = defaultdict(list)
    next_key = 0

    for a_position in a.vertices:
        b_index = _closest_index(a_position, b.vertices, b_grid, tolerance)
        if b_index is None:
            continue

        position = (a_position + b.vertices[b_index]) * 0.5
        key = _closest_position_key(position, shared_positions, shared_grid, tolerance)
        if key is None:
            key = next_key
            next_key += 1
            shared_positions[key] = position
            shared_grid[_bucket(position, tolerance)].append(key)

    if not shared_positions:
        return {}, {}, {}

    a_to_key = _map_vertices_to_shared_positions(a.vertices, shared_positions, shared_grid, tolerance)
    b_to_key = _map_vertices_to_shared_positions(b.vertices, shared_positions, shared_grid, tolerance)
    return shared_positions, a_to_key, b_to_key


def _shared_edges(data: StructureObject, vertex_to_key: dict[int, int]) -> set[tuple[int, int]]:
    edges = set()
    for edge in data.mesh.edges:
        key_a = vertex_to_key.get(edge.vertices[0])
        key_b = vertex_to_key.get(edge.vertices[1])
        if key_a is not None and key_b is not None and key_a != key_b:
            edges.add(tuple(sorted((key_a, key_b))))

    return edges


def _shared_face_loops(data: StructureObject, vertex_to_key: dict[int, int], positions: dict[int, Vector], min_area: float) -> list[tuple[int, ...]]:
    loops = []
    seen = set()
    for polygon in data.mesh.polygons:
        loop = []
        for vertex_index in polygon.vertices:
            key = vertex_to_key.get(vertex_index)
            if key is None:
                break
            if not loop or loop[-1] != key:
                loop.append(key)
        else:
            if len(loop) > 1 and loop[0] == loop[-1]:
                loop.pop()
            if len(set(loop)) < 3:
                continue

            signature = frozenset(loop)
            if signature in seen:
                continue
            if _polygon_area([positions[key] for key in loop]) <= min_area:
                continue

            seen.add(signature)
            loops.append(tuple(loop))

    return loops


def _fill_component_faces(
    component_keys: set[int],
    component_edges: set[tuple[int, int]],
    positions: dict[int, Vector],
    min_area: float,
    tolerance: float,
) -> list[tuple[int, ...]]:
    if len(component_keys) < 3:
        return []

    if not component_edges:
        loop = _sorted_planar_loop(component_keys, positions, tolerance)
        return [loop] if loop and _polygon_area([positions[key] for key in loop]) > min_area else []

    edge_degrees = defaultdict(int)
    for key_a, key_b in component_edges:
        edge_degrees[key_a] += 1
        edge_degrees[key_b] += 1

    can_planar_fallback = all(edge_degrees[key] >= 2 for key in component_keys)
    bm = bmesh.new()
    bm_verts = {}
    try:
        for key in component_keys:
            bm_verts[key] = bm.verts.new(positions[key])
        bm.verts.ensure_lookup_table()

        geom = list(bm.verts)
        for key_a, key_b in component_edges:
            try:
                edge = bm.edges.new((bm_verts[key_a], bm_verts[key_b]))
            except ValueError:
                continue
            geom.append(edge)

        bmesh.ops.contextual_create(bm, geom=geom)
        bm.faces.ensure_lookup_table()

        vert_to_key = {vert: key for key, vert in bm_verts.items()}
        loops = []
        for face in bm.faces:
            loop = tuple(vert_to_key[vert] for vert in face.verts if vert in vert_to_key)
            if len(set(loop)) >= 3 and _polygon_area([positions[key] for key in loop]) > min_area:
                loops.append(loop)

        if loops:
            return loops
    finally:
        bm.free()

    if can_planar_fallback:
        loop = _sorted_planar_loop(component_keys, positions, tolerance)
        return [loop] if loop and _polygon_area([positions[key] for key in loop]) > min_area else []

    return []


def _create_seam_object(
    context: bpy.types.Context,
    a: StructureObject,
    b: StructureObject,
    component: SeamComponent,
    apply_materials: bool,
):
    mesh, origin = _mesh_from_component(component)
    if mesh is None:
        return None

    _recalculate_normals(mesh)
    front, back = _front_back_from_normals(mesh, origin, a, b, component)
    _orient_mesh_faces(
        mesh,
        origin,
        component.a_side_point if front is a else component.b_side_point,
        component.b_side_point if front is a else component.a_side_point,
    )

    seam = bpy.data.objects.new(f"seam({front.region}:{back.region})", mesh)
    seam.matrix_world = Matrix.Translation(origin)
    seam.data.nwo.mesh_type = SEAM_MESH_TYPE
    seam.nwo.region_name = front.region
    seam.nwo.permutation_name = front.permutation
    seam.nwo.seam_back = back.region
    context.scene.collection.objects.link(seam)

    if apply_materials:
        apply_props_material(seam, "Seam")

    return seam


def _mesh_from_component(component: SeamComponent):
    key_to_index = {}
    ordered_keys = []
    for loop in component.face_loops:
        for key in loop:
            if key not in key_to_index:
                key_to_index[key] = len(ordered_keys)
                ordered_keys.append(key)

    if len(ordered_keys) < 3:
        return None, None

    origin = _average([component.positions[key] for key in ordered_keys])
    vertices = [component.positions[key] - origin for key in ordered_keys]
    faces = [[key_to_index[key] for key in loop] for loop in component.face_loops]
    mesh = bpy.data.meshes.new("seam")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(clean_customdata=False)
    mesh.update(calc_edges=True)

    if not mesh.polygons:
        bpy.data.meshes.remove(mesh)
        return None, None

    return mesh, origin


def _front_back_from_normals(mesh: bpy.types.Mesh, origin: Vector, a: StructureObject, b: StructureObject, component: SeamComponent):
    score_a = 0.0
    score_b = 0.0
    for polygon in mesh.polygons:
        if not polygon.normal.length_squared:
            continue
        face_center = origin + polygon.center
        score_a += polygon.normal.dot(component.a_side_point - face_center)
        score_b += polygon.normal.dot(component.b_side_point - face_center)

    return (a, b) if score_a >= score_b else (b, a)


def _orient_mesh_faces(mesh: bpy.types.Mesh, origin: Vector, front_point: Vector, back_point: Vector):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            normal = face.normal
            if not normal.length_squared:
                continue
            face_center = origin + face.calc_center_median()
            front_score = normal.dot(front_point - face_center)
            back_score = normal.dot(back_point - face_center)
            if front_score < back_score:
                face.normal_flip()

        bm.to_mesh(mesh)
    finally:
        bm.free()

    mesh.update(calc_edges=True)


def _recalculate_normals(mesh: bpy.types.Mesh):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(mesh)
    finally:
        bm.free()

    mesh.update(calc_edges=True)


def _component_adjacency(keys, edges: set[tuple[int, int]], face_loops: list[tuple[int, ...]]):
    adjacency = {key: set() for key in keys}
    for key_a, key_b in edges:
        adjacency[key_a].add(key_b)
        adjacency[key_b].add(key_a)

    for loop in face_loops:
        for index, key_a in enumerate(loop):
            key_b = loop[(index + 1) % len(loop)]
            if key_a == key_b:
                continue
            adjacency[key_a].add(key_b)
            adjacency[key_b].add(key_a)

    return adjacency


def _connected_components(keys, adjacency: dict[int, set[int]]) -> list[set[int]]:
    keys = set(keys)
    if len(keys) >= 3 and not any(adjacency.values()):
        return [keys]

    components = []
    remaining = set(keys)
    while remaining:
        start = remaining.pop()
        component = {start}
        stack = [start]
        while stack:
            key = stack.pop()
            for other in adjacency.get(key, ()):
                if other in remaining:
                    remaining.remove(other)
                    component.add(other)
                    stack.append(other)

        components.append(component)

    return components


def _component_side_point(
    data: StructureObject,
    vertex_to_key: dict[int, int],
    component_keys: set[int],
    positions: dict[int, Vector],
) -> Vector:
    samples = []
    for edge in data.mesh.edges:
        vert_a, vert_b = edge.vertices
        key_a = vertex_to_key.get(vert_a)
        key_b = vertex_to_key.get(vert_b)
        if key_a in component_keys and key_b not in component_keys:
            samples.append(data.vertices[vert_b])
        elif key_b in component_keys and key_a not in component_keys:
            samples.append(data.vertices[vert_a])

    if samples:
        return _average(samples)

    component_center = _average(positions.values())
    fallback = None
    fallback_distance = float("inf")
    for index, position in enumerate(data.vertices):
        if vertex_to_key.get(index) in component_keys:
            continue
        distance = (position - component_center).length_squared
        if distance < fallback_distance:
            fallback = position
            fallback_distance = distance

    return fallback if fallback is not None else data.center


def _existing_seam_signatures(seams: list[bpy.types.Object], tolerance: float):
    component_signatures = set()
    face_signatures = set()
    for seam in seams:
        mesh = seam.data
        if not mesh.vertices:
            continue

        vertex_keys = [_signature_key(seam.matrix_world @ vertex.co, tolerance) for vertex in mesh.vertices]
        component_signatures.add(frozenset(vertex_keys))
        for polygon in mesh.polygons:
            signature = frozenset(vertex_keys[index] for index in polygon.vertices)
            if len(signature) >= 3:
                face_signatures.add(signature)

    return component_signatures, face_signatures


def _component_signatures(component: SeamComponent, tolerance: float):
    component_signature = frozenset(_signature_key(position, tolerance) for position in component.positions.values())
    face_signatures = {
        frozenset(_signature_key(component.positions[key], tolerance) for key in loop)
        for loop in component.face_loops
    }
    return component_signature, face_signatures


def _dedupe_face_loops(face_loops: list[tuple[int, ...]], positions: dict[int, Vector], min_area: float) -> list[tuple[int, ...]]:
    deduped = []
    seen = set()
    for loop in face_loops:
        clean_loop = []
        for key in loop:
            if not clean_loop or clean_loop[-1] != key:
                clean_loop.append(key)
        if len(clean_loop) > 1 and clean_loop[0] == clean_loop[-1]:
            clean_loop.pop()
        if len(set(clean_loop)) < 3:
            continue

        signature = frozenset(clean_loop)
        if signature in seen:
            continue
        if _polygon_area([positions[key] for key in clean_loop]) <= min_area:
            continue

        seen.add(signature)
        deduped.append(tuple(clean_loop))

    return deduped


def _position_grid(items, tolerance: float):
    grid = defaultdict(list)
    for index, position in items:
        grid[_bucket(position, tolerance)].append((index, position))

    return grid


def _map_vertices_to_shared_positions(
    vertices: list[Vector],
    positions: dict[int, Vector],
    position_grid,
    tolerance: float,
) -> dict[int, int]:
    vertex_to_key = {}
    for index, position in enumerate(vertices):
        key = _closest_position_key(position, positions, position_grid, tolerance)
        if key is not None:
            vertex_to_key[index] = key

    return vertex_to_key


def _closest_index(position: Vector, vertices: list[Vector], grid, tolerance: float):
    bucket = _bucket(position, tolerance)
    tolerance_squared = tolerance * tolerance
    closest_index = None
    closest_distance = tolerance_squared
    for neighbor in _neighbor_buckets(bucket):
        for index, other_position in grid.get(neighbor, ()):
            distance = (position - other_position).length_squared
            if distance <= closest_distance:
                closest_index = index
                closest_distance = distance

    return closest_index


def _closest_position_key(position: Vector, positions: dict[int, Vector], grid, tolerance: float):
    bucket = _bucket(position, tolerance)
    tolerance_squared = tolerance * tolerance
    closest_key = None
    closest_distance = tolerance_squared
    for neighbor in _neighbor_buckets(bucket):
        for key in grid.get(neighbor, ()):
            distance = (position - positions[key]).length_squared
            if distance <= closest_distance:
                closest_key = key
                closest_distance = distance

    return closest_key


def _neighbor_buckets(bucket: tuple[int, int, int]):
    for offset in product((-1, 0, 1), repeat=3):
        yield bucket[0] + offset[0], bucket[1] + offset[1], bucket[2] + offset[2]


def _bucket(position: Vector, tolerance: float) -> tuple[int, int, int]:
    return (
        floor(position.x / tolerance),
        floor(position.y / tolerance),
        floor(position.z / tolerance),
    )


def _signature_key(position: Vector, tolerance: float) -> tuple[int, int, int]:
    return (
        round(position.x / tolerance),
        round(position.y / tolerance),
        round(position.z / tolerance),
    )


def _sorted_planar_loop(keys: set[int], positions: dict[int, Vector], tolerance: float):
    points = [positions[key] for key in keys]
    normal = _normal_from_points(points)
    if normal is None:
        return None

    origin = points[0]
    if any(abs(normal.dot(point - origin)) > tolerance for point in points):
        return None

    center = _average(points)
    axis_x = None
    for point in points:
        delta = point - center
        if delta.length_squared > 0:
            axis_x = delta
            break
    if axis_x is None:
        return None

    axis_x.normalize()
    axis_y = normal.cross(axis_x)
    axis_y.normalize()

    return tuple(
        key for key, _angle in sorted(
            (
                (key, atan2((positions[key] - center).dot(axis_y), (positions[key] - center).dot(axis_x)))
                for key in keys
            ),
            key=lambda item: item[1],
        )
    )


def _normal_from_points(points: list[Vector]):
    for first_index, first in enumerate(points):
        for second_index in range(first_index + 1, len(points)):
            first_edge = points[second_index] - first
            if not first_edge.length_squared:
                continue
            for third_index in range(second_index + 1, len(points)):
                normal = first_edge.cross(points[third_index] - first)
                if normal.length_squared:
                    normal.normalize()
                    return normal

    return None


def _polygon_area(points: list[Vector]) -> float:
    if len(points) < 3:
        return 0.0

    origin = points[0]
    area = 0.0
    for index in range(1, len(points) - 1):
        area += (points[index] - origin).cross(points[index + 1] - origin).length * 0.5

    return area


def _average(points) -> Vector:
    points = list(points)
    if not points:
        return Vector()

    return sum(points, Vector()) / len(points)


def _object_center(ob: bpy.types.Object) -> Vector:
    return _average(ob.matrix_world @ Vector(corner) for corner in ob.bound_box)
