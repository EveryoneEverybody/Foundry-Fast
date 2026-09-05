"""Validation and mesh partitioning for the H3 bridge format. No Blender imports."""
from collections import OrderedDict
import json
import math
from pathlib import Path, PurePosixPath

FORMAT = "foundry.h3-object"
VERSION = 1


def vector(value, size, label):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f"{label}: expected {size} numbers")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
        raise ValueError(f"{label}: non-finite or non-numeric value")
    return value


def index(value, count, label, allow_none=False):
    minimum = -1 if allow_none else 0
    if type(value) is not int or not minimum <= value < count:
        raise ValueError(f"{label}: invalid index {value}")


def transform(value, label):
    vector(value["position"], 3, label + " position")
    q = vector(value["rotation"], 4, label + " rotation")
    if sum(x*x for x in q) < 1e-12:
        raise ValueError(f"{label}: zero quaternion")


def validate_nodes(nodes):
    names = set()
    for i, node in enumerate(nodes):
        name = node["name"]
        if not isinstance(name, str) or not name or "\x00" in name or len(name.encode("utf-8")) > 63:
            raise ValueError(f"Node {i}: invalid or overlong bone name")
        if name in names:
            raise ValueError(f"Duplicate bone name: {name}")
        names.add(name)
        index(node["parent"], len(nodes), name + " parent", True)
        transform(node, name)
    for i in range(len(nodes)):
        seen = set()
        while i != -1:
            if i in seen:
                raise ValueError("Cycle in source skeleton")
            seen.add(i)
            i = nodes[i]["parent"]


def material_partition(label):
    parts = label.split()
    if len(parts) == 3 and parts[0].startswith("(") and parts[0].endswith(")"):
        return parts[2], parts[1], ""
    if len(parts) == 4 and parts[0].startswith("(") and parts[0].endswith(")"):
        return parts[3], parts[2], parts[1]
    raise ValueError(f"Unrecognized material region/permutation label: {label!r}")


def validate_mesh(mesh, skeleton_names):
    nodes = mesh["nodes"]
    validate_nodes(nodes)
    if any(n["name"] not in skeleton_names for n in nodes):
        raise ValueError("Dependency contains bones absent from the render skeleton")
    for material in mesh["materials"]:
        if not isinstance(material["name"], str):
            raise ValueError("Material name must be text")
        material_partition(material["label"])
    vertices = mesh["vertices"]
    for vertex in vertices:
        vector(vertex["position"], 3, "vertex position")
        vector(vertex["normal"], 3, "vertex normal")
        seen = set()
        for weight in vertex["weights"]:
            vector(weight, 2, "vertex weight")
            bone, amount = weight
            index(bone, len(nodes), "weight bone")
            if bone in seen or amount < 0:
                raise ValueError("Repeated bone or negative skin weight")
            seen.add(bone)
        for uv in vertex["uvs"]:
            vector(uv, 2, "UV")
        if vertex.get("color") is not None:
            vector(vertex["color"], 3, "vertex color")
    for triangle in mesh["triangles"]:
        index(triangle["material"], len(mesh["materials"]), "triangle material")
        indices = triangle["vertices"]
        if len(indices) != 3 or len(set(indices)) != 3:
            raise ValueError("Invalid triangle")
        for value in indices:
            index(value, len(vertices), "triangle vertex")
    for marker in mesh["markers"]:
        if not isinstance(marker["name"], str) or not marker["name"]:
            raise ValueError("Empty marker name")
        transform(marker, "marker")
        index(marker["node"], len(nodes), "marker bone", True)
        vector([marker["radius"]], 1, "marker radius")


def validate_payload(payload):
    if (payload.get("format"), payload.get("version"), payload.get("units"), payload.get("game")) != (
        FORMAT, VERSION, "jms_x100", "halo3_mcc"
    ):
        raise ValueError("Unsupported H3 bridge format, version, units or source game")
    if not isinstance(payload.get("name"), str) or not payload["name"]:
        raise ValueError("Missing asset name")
    skeleton = payload["render"]["nodes"]
    names = {node["name"] for node in skeleton}
    validate_mesh(payload["render"], names)
    if not payload["render"]["triangles"]:
        raise ValueError("No render triangles")
    if payload.get("collision") is not None:
        validate_mesh(payload["collision"], names)
    if payload.get("physics") is not None:
        for shape in payload["physics"]["shapes"]:
            transform(shape, "physics shape")
            index(shape["node"], len(skeleton), "physics bone", True)
            if shape["kind"] == "sphere":
                vector([shape["radius"]], 1, "sphere radius")
                if shape["radius"] <= 0:
                    raise ValueError("Non-positive sphere radius")
            elif shape["kind"] == "box":
                vector(shape["size"], 3, "box size")
                if min(shape["size"]) <= 0:
                    raise ValueError("Non-positive box size")
            elif shape["kind"] == "convex":
                if len(shape["vertices"]) < 4:
                    raise ValueError("Convex shape needs at least four points")
                for point in shape["vertices"]:
                    vector(point, 3, "convex point")
            else:
                raise ValueError(f"Unsupported physics shape: {shape['kind']}")
    return payload


def load_payload(path):
    def invalid_constant(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    with Path(path).open("r", encoding="utf-8") as stream:
        payload = json.load(stream, parse_constant=invalid_constant)
    return validate_payload(payload)


def groups(mesh, collision=False):
    """Keep region, permutation, LOD and rigid collision attachments separate."""
    result = OrderedDict()
    for triangle in mesh["triangles"]:
        material = mesh["materials"][triangle["material"]]
        region, permutation, lod = material_partition(material["label"])
        node = -1
        if collision:
            bones = set()
            for vi in triangle["vertices"]:
                bones.update(b for b, w in mesh["vertices"][vi]["weights"] if w > 0)
            if len(bones) > 1:
                raise ValueError("Collision triangle spans several bones")
            if bones:
                node = bones.pop()
        key = region, permutation, lod, node
        result.setdefault(key, []).append(triangle)
    return result


def compact_mesh(mesh, triangles):
    """Remap existing indices without welding coincident vertices."""
    remap = {}
    source_indices = []
    faces = []
    for triangle in triangles:
        face = []
        for old in triangle["vertices"]:
            if old not in remap:
                remap[old] = len(source_indices)
                source_indices.append(old)
            face.append(remap[old])
        faces.append(face)
    return [mesh["vertices"][i] for i in source_indices], faces


def shader_candidates(name, paths):
    """Ambiguous basenames stay unresolved rather than picking an arbitrary shader."""
    return sorted({p for p in paths if PurePosixPath(p.replace("\\", "/")).stem.casefold() == name.casefold()})


def find_tags_root(path):
    path = Path(path).resolve(strict=True)
    for parent in path.parents:
        if parent.name.casefold() == "tags":
            return parent
    raise ValueError("No tags directory in source path. Set Halo 3 Tags Directory explicitly")
