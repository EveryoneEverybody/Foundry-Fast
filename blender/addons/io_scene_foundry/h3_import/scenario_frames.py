"""Detached object/node reference transforms in unscaled H3 world units.

H3 ai_reference_frame_block contains an object identifier and node index.
Hierarchy belongs to placements and model nodes, not to a fictitious frame
parent field. Projection axis/sign are retained for pathfinding consumers;
this module transforms three-dimensional authored points, not 2D nav polygons.
"""
import math
from .scenario_scene import numbers


def identity():
    return [[float(i == j) for j in range(4)] for i in range(4)]


def multiply(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def transform(matrix, point, vector=False):
    numbers(list(point), 3)
    return [sum(matrix[i][j] * point[j] for j in range(3)) + (0 if vector else matrix[i][3]) for i in range(3)]


def quaternion_matrix(position, rotation, scale=1.):
    numbers(list(position), 3); numbers(list(rotation), 4); numbers([scale], 1)
    length = math.sqrt(sum(v*v for v in rotation))
    if length < 1e-8 or scale <= 0:
        raise ValueError('Invalid source rotation or nonpositive scale')
    w, x, y, z = (v / length for v in rotation)
    matrix = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w), position[0]],
              [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w), position[1]],
              [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y), position[2]],
              [0., 0., 0., 1.]]
    for i in range(3):
        for j in range(3): matrix[i][j] *= scale
    return matrix


def placement_matrix(row):
    yaw, pitch, roll = numbers(row['rotation'], 3)
    # Same ZYX convention as Foundry's existing ScenarioObject.
    qx = [math.cos(roll/2), math.sin(roll/2), 0, 0]
    qy = [math.cos(-pitch/2), 0, math.sin(-pitch/2), 0]
    qz = [math.cos(yaw/2), 0, 0, math.sin(yaw/2)]
    matrix = multiply(multiply(quaternion_matrix([0,0,0], qz), quaternion_matrix([0,0,0], qy)), quaternion_matrix([0,0,0], qx))
    for i in range(3):
        matrix[i][3] = numbers(row.get('source_position', row['position']), 3)[i]
        for j in range(3): matrix[i][j] *= row['scale']
    if row['scale'] <= 0: raise ValueError('Nonpositive placement scale is unsupported')
    return matrix


def enum_value(value):
    return value.get('value') if isinstance(value, dict) else value


def object_identifier(value):
    keys = ('unique id', 'origin bsp index', 'type', 'source')
    result = tuple(enum_value(value.get(k)) for k in keys)
    if any(type(v) is not int for v in result) or result[0] == -1:
        raise ValueError('Incomplete source object identifier')
    return result


def node_matrix(payload, node):
    nodes = payload['render']['nodes']
    if type(node) is not int or node < -1 or node >= len(nodes):
        raise ValueError(f'Invalid reference node {node}; model has {len(nodes)} nodes')
    if node == -1: return identity()
    # JMS nodes are already in model space. Validate ancestry but do not
    # multiply it twice. The same matrices construct BuildSession edit bones.
    active = set()
    ancestor = node
    while ancestor != -1:
        if type(ancestor) is not int or ancestor < 0 or ancestor >= len(nodes) or ancestor in active:
            raise ValueError('Missing or cyclic model node hierarchy')
        active.add(ancestor); ancestor = nodes[ancestor]['parent']
    row = nodes[node]
    return quaternion_matrix([v / 100. for v in row['position']], row['rotation'])


def marker_matrix(payload, name):
    if not name: return identity()
    matches = [m for m in payload['render'].get('markers', []) if m['name'] == name]
    if len(matches) != 1:
        raise ValueError(f'Attachment marker {name!r}: expected one source marker, found {len(matches)}; permutation filtering unresolved')
    marker = matches[0]
    return multiply(node_matrix(payload, marker['node']),
                    quaternion_matrix([v/100. for v in marker['position']], marker['rotation']))


def inverse_rigid(matrix):
    # Marker transforms have no scale. Never use this for placement matrices.
    inverse = identity()
    for i in range(3):
        for j in range(3): inverse[i][j] = matrix[j][i]
        inverse[i][3] = -sum(inverse[i][j]*matrix[j][3] for j in range(3))
    return inverse


class FrameResolver:
    def __init__(self, index, placements, payloads=None):
        self.index = index
        self.placements = placements
        self.payloads = payloads or {}
        self.frames = dict(index.elements('', 'reference frames'))
        self.by_identifier, self.by_name = {}, {}
        self.cache, self.object_cache = {}, {}
        self.resolved, self.failures = {}, {}
        for row in placements:
            try:
                key = object_identifier(row['metadata'].get('object id', {}))
                self.by_identifier.setdefault(key, []).append(row)
            except ValueError: pass
            if row['name_index'] >= 0: self.by_name.setdefault(row['name_index'], []).append(row)

    def payload(self, row):
        data = self.payloads.get(row['source_tag'])
        if data is None: raise ValueError(f"Source model unavailable for {row['source_tag']}")
        return data

    def object_world(self, row, active=None):
        key = row['address']
        if key in self.object_cache: return self.object_cache[key]
        active = set() if active is None else set(active)
        if key in active or len(active) >= 96:
            raise ValueError('Cyclic or excessively deep placement hierarchy')
        active.add(key)
        if enum_value(row['metadata']['object'].get('transform flags', 0)):
            raise ValueError('Mirrored or unknown source transform flags')
        local = placement_matrix(row)
        parent = row['parent_name_index']
        if parent != -1:
            matches = self.by_name.get(parent, [])
            if len(matches) != 1: raise ValueError(f'Missing or ambiguous parent object name index {parent}')
            parent_row = matches[0]
            if parent_row.get('stored_pose'): raise ValueError('Parent attachment uses an unresolved stored node pose')
            parent_marker = marker_matrix(self.payload(parent_row), row['parent_marker'])
            child_marker = marker_matrix(self.payload(row), row['connection_marker'])
            local = multiply(multiply(multiply(self.object_world(parent_row, active), parent_marker), local), inverse_rigid(child_marker))
        self.object_cache[key] = local
        return local

    def matrix(self, frame):
        if type(frame) is not int or frame < -1: raise ValueError(f'Invalid reference frame {frame!r}')
        if frame == -1: return identity()
        if frame in self.cache: return self.cache[frame]
        if frame not in self.frames: raise ValueError(f'Missing reference frame {frame}')
        address = self.frames[frame]
        object_id = self.index.struct(address, 'object id')
        key = object_identifier(self.index.metadata(object_id))
        matches = self.by_identifier.get(key, [])
        if len(matches) != 1: raise ValueError(f'Reference frame {frame}: object identifier {key} has {len(matches)} placements')
        row = matches[0]
        node = self.index.value(address, 'node index')
        if row.get('stored_pose') and node != -1:
            raise ValueError(f'Reference frame {frame}: node {node} requires an unresolved stored pose')
        matrix = multiply(self.object_world(row), node_matrix(self.payload(row), node))
        self.cache[frame] = matrix
        self.resolved[frame] = dict(address=address, object_address=row['address'], source_tag=row['source_tag'],
                                    node_index=node, matrix=matrix, basis='placed model rest pose',
                                    source_fields=self.index.metadata(address), object_id=self.index.metadata(object_id))
        return matrix

    def point(self, point, frame):
        try: return transform(self.matrix(frame), point)
        except (KeyError, TypeError, ValueError) as error:
            self.failures[str(frame)] = str(error)
            raise ValueError(f'Reference frame {frame} unresolved: {error}') from error
