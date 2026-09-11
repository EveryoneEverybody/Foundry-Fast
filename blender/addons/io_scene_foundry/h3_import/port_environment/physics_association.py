"""Source-indexed rigid-shape ownership; no Havok runtime bytes are copied."""
from collections import Counter
from copy import deepcopy

from . import object_ir as ir

RULE = 'SOURCE_INDEXED_PHYSICS_SHAPE_BODY'
DECODER = '5d0509fb75eadb96ac7774542ca0b2c10aed7b00'
TABLES = {'sphere': 'spheres', 'box': 'boxes', 'polyhedron': 'polyhedra',
          'list': 'lists', 'mopp': 'mopps'}
KINDS = {'sphere': 'sphere', 'box': 'box', 'convex': 'polyhedron'}


def elements(rows, name):
    result = (ir.field(rows, name) or {}).get('elements', [])
    if [r['source_index'] for r in result] != list(range(len(result))):
        raise ValueError('Physics source table indices are not contiguous: ' + name)
    return result


def value(rows, name):
    return ir.scalar(ir.field(rows, name))


def struct(rows, name):
    field = ir.field(rows, name)
    if field is None or 'fields' not in field:
        raise ValueError('Missing physics source struct: ' + name)
    return field['fields']


def reference(rows):
    data = struct(rows, 'shape reference')
    kind = ir.field(data, 'shape type')['value']['name']
    index = value(data, 'shape')
    if kind not in TABLES:
        raise ValueError('Physics shape type requires a separate adapter: ' + kind)
    if type(index) is not int or index < 0:
        raise ValueError('Invalid physics shape reference index')
    return kind, index


def source_graph(source):
    """Expand checked list slices and retain every body and reference edge."""
    tables = {kind: elements(source, name) for kind, name in TABLES.items()}
    children = elements(source, 'list shapes')
    slices = []
    offset = 0
    for row in tables['list']:
        count = value(row['fields'], 'child shapes size')
        if type(count) is not int or count <= 0 or offset + count > len(children):
            raise ValueError('Invalid physics list child slice')
        slices.append(children[offset:offset + count])
        offset += count
    if offset != len(children):
        raise ValueError('Physics lists do not cover the list-shapes table exactly')

    def expand(ref, path):
        kind, index = ref
        if ref in path:
            raise ValueError('Cyclic physics shape references')
        if index >= len(tables[kind]):
            raise ValueError('Physics shape reference outside source table')
        path = (*path, ref)
        if kind == 'list':
            return [leaf for child in slices[index]
                    for leaf in expand(reference(child['fields']), path)]
        if kind == 'mopp':
            index = value(tables[kind][index]['fields'], 'list')
            if type(index) is not int or index < 0:
                raise ValueError('Invalid physics MOPP list reference')
            return expand(('list', index), path)
        return [(ref, path)]

    bodies = elements(source, 'rigid bodies')
    owners = {}
    body_rows = []
    for body in bodies:
        root = reference(body['fields'])
        leaves = expand(root, ())
        for leaf, path in leaves:
            if leaf in owners:
                raise ValueError('Physics leaf has repeated or multiple body ownership: ' + str(leaf))
            owners[leaf] = dict(body_index=body['source_index'], reference_path=path)
        body_rows.append(dict(source_index=body['source_index'], shape_reference=root,
                              leaves=[ref for ref, _ in leaves]))

    # Cross-check the inverse region/permutation table, not just body node names.
    inverse = {}
    for region in elements(source, 'regions'):
        for permutation in elements(region['fields'], 'permutations'):
            for link in elements(permutation['fields'], 'rigid bodies'):
                index = value(link['fields'], 'rigid body')
                if type(index) is not int or not 0 <= index < len(bodies) or index in inverse:
                    raise ValueError('Invalid or repeated physics region body reference')
                inverse[index] = (region['source_index'], permutation['source_index'])
    for body in bodies:
        expected = (value(body['fields'], 'region'), value(body['fields'], 'permutattion'))
        if expected != inverse.get(body['source_index']):
            raise ValueError('Physics region/permutation body references disagree')
    return owners, body_rows


def bind(source, payload):
    """Bind the pinned decoder's complete ordered tables to exact source indices.

    blam-tags 5d0509f jms.rs:2490-2630 emits spheres, boxes and polyhedra in
    table order. Missing structs can skip rows, so cardinality and each ordered
    source name/material are required. No name search or node-only fallback.
    The caller verifies the immutable source and decoded asset hashes first.
    """
    physics = payload['physics']
    if payload.get('decoder') != DECODER or physics.get('shape_space') != 'node_local':
        raise ValueError('Physics decoded source-index contract is unverified')
    if any(physics.get(k, 0) for k in ('capsules_in_source', 'ragdolls_in_source', 'hinges_in_source')):
        raise ValueError('Physics capsule/constraint authoring remains deferred')
    owners, bodies = source_graph(source)
    source_nodes = elements(source, 'nodes')
    if [value(r['fields'], 'name') for r in source_nodes] != [r['name'] for r in physics['nodes']]:
        raise ValueError('Physics source/decoded node identities differ')
    from .native_physics import source_bodies
    identities = {body['source_index']: identity for identity, body in source_bodies(source).items()}
    counts = Counter(s['kind'] for s in physics['shapes'])
    if counts.keys() - KINDS.keys():
        raise ValueError('Unsupported decoded physics primitive')
    for kind, source_kind in KINDS.items():
        if counts[kind] != len(elements(source, TABLES[source_kind])):
            raise ValueError('Decoded/source physics primitive table counts differ: ' + kind)
    result = []
    seen = Counter()
    for shape in physics['shapes']:
        kind = KINDS[shape['kind']]
        index = seen[kind]
        seen[kind] += 1
        ref = (kind, index)
        base = struct(elements(source, TABLES[kind])[index]['fields'], 'base')
        if (shape['name'], shape['material']) != (value(base, 'name'), value(base, 'material')):
            raise ValueError('Decoded/source ordered physics shape identity differs')
        if ref not in owners:
            raise ValueError('Decoded physics shape has no source body owner: ' + str(ref))
        owner = owners[ref]
        body = bodies[owner['body_index']]
        authored = elements(source, 'rigid bodies')[body['source_index']]['fields']
        if shape['node'] != value(authored, 'node'):
            raise ValueError('Decoded physics shape node differs from source owner')
        identity = identities[body['source_index']]
        if identity[1] is None or identity[2] is None:
            raise ValueError('Unassigned source physics region/permutation needs a separate adapter')
        result.append(dict(deepcopy(shape), source_shape_type=kind, source_shape_index=index,
            source_body_index=body['source_index'], source_body_identity=identity,
            source_reference_path=owner['reference_path'], association_rule=RULE))
    if {(s['source_shape_type'], s['source_shape_index']) for s in result} != owners.keys():
        raise ValueError('Source physics leaves are not completely decoded')
    return result


def native_rows(tag):
    """Read semantic indices from ManagedBlam; ignore runtime pointer fields."""
    def f(name, data): return dict(name=name, type='value', value=data)
    def block(name, rows):
        return dict(name=name, type='block', elements=[dict(source_index=i, fields=r) for i, r in enumerate(rows)])
    def structure(name, rows): return dict(name=name, type='struct', fields=rows)
    def string(row, name): return row.SelectField(name).GetStringData()
    def index(row, name): return int(row.SelectField(name).Value)
    def ref(row):
        item = row.SelectField('shape reference/shape type')
        return structure('shape reference', [f('shape type', dict(name=str(item.Items[item.Value].EnumName))),
            f('shape', index(row, 'shape reference/shape'))])
    result = [block('nodes', [[f('name', string(n, 'name'))] for n in tag.SelectField('nodes').Elements]),
        block('materials', [[f('name', string(m, 'name'))] for m in tag.SelectField('materials').Elements]),
        block('rigid bodies', [[f(name, index(b, name)) for name in ('node', 'region', 'permutattion')] + [ref(b)]
              for b in tag.SelectField('rigid bodies').Elements]),
        block('list shapes', [[ref(c)] for c in tag.SelectField('list shapes').Elements]),
        block('lists', [[f('child shapes size', int(c.SelectField('child shapes size').Data))]
              for c in tag.SelectField('lists').Elements]),
        block('mopps', [[f('list', index(c, 'list'))] for c in tag.SelectField('mopps').Elements])]
    for name in ('spheres', 'boxes', 'polyhedra'):
        result.append(block(name, [[structure('base', [f('name', string(s, 'base/name')),
            f('material', index(s, 'base/material'))])] for s in tag.SelectField(name).Elements]))
    result.append(block('regions', [[f('name', string(r, 'name')), block('permutations', [
        [f('name', string(p, 'name')), block('rigid bodies', [[f('rigid body', index(b, 'rigid body'))]
            for b in p.SelectField('rigid bodies').Elements])] for p in r.SelectField('permutations').Elements])]
        for r in tag.SelectField('regions').Elements]))
    return result


def compare_native(source, payload, native, *, receipt_shape_names=None):
    """Compare leaf ownership by source-labelled shape and full body identity."""
    expected_shapes = bind(source, payload)
    owners, bodies = source_graph(native)
    from .native_physics import source_bodies
    native_identities = {b['source_index']: identity for identity, b in source_bodies(native).items()}
    materials = elements(native, 'materials')
    actual = {}
    for kind in KINDS.values():
        for row in elements(native, TABLES[kind]):
            base = struct(row['fields'], 'base')
            key = (kind, value(base, 'name'))
            material = value(base, 'material')
            if key in actual or not 0 <= material < len(materials):
                raise ValueError('Native physics shape/material identity is ambiguous')
            owner = owners.get((kind, row['source_index']))
            if owner is None: raise ValueError('Native physics leaf is unowned')
            actual[key] = dict(native_shape_index=row['source_index'],
                native_body_index=owner['body_index'], native_reference_path=owner['reference_path'],
                identity=native_identities[owner['body_index']], material=value(materials[material]['fields'], 'name'))
    expected = {}
    source_materials = elements(source, 'materials')
    for shape in expected_shapes:
        kind, index = shape['source_shape_type'], shape['source_shape_index']
        name = 'h3_' + kind + '_' + str(index)
        if receipt_shape_names is not None:
            if (kind,index) not in receipt_shape_names:
                raise ValueError('Receipt lacks source physics leaf identity')
            name = receipt_shape_names[(kind,index)]
        key = (kind, name)
        if key in expected:
            raise ValueError('Receipt physics leaf names are ambiguous')
        expected[key] = dict(identity=shape['source_body_identity'],
            material=value(source_materials[shape['material']]['fields'], 'name'))
    if actual.keys() != expected.keys():
        raise ValueError('Native/source physics leaf identities differ')
    for key, wanted in expected.items():
        if any(actual[key][field] != val for field, val in wanted.items()):
            raise ValueError('Native/source physics leaf ownership or material differs: ' + str(key))
    if set(native_identities.values()) != set(source_bodies(source)):
        raise ValueError('Native/source physics body identities differ')
    return dict(rule=RULE, status='NATIVE_READBACK_VERIFIED', body_count=len(bodies),
        leaf_count=len(actual), leaves=[dict(source_shape_type=k[0], native_shape_name=k[1], **v)
                                       for k, v in sorted(actual.items())], runtime_status='NOT_TESTED')


def validate_native(tag, source, payload, *, receipt_shape_names=None):
    return compare_native(source, payload, native_rows(tag), receipt_shape_names=receipt_shape_names)


def legacy_receipt_names(source, payload, receipt):
    """Recover old exporter labels only from an exact compiled source receipt.

    This is readback compatibility, not a writer fallback. The caller must
    separately verify the receipt's source/output hashes before trusting it.
    Full source body/list/primitive/region/permutation checks still apply.
    """
    shapes = bind(source, payload)
    recorded = receipt.get('physics_authoring', [])
    if receipt.get('status') != 'NATIVE_COMPILED' or len(recorded) != len(shapes):
        raise ValueError('Legacy compiled physics receipt is incomplete')
    result = {}
    for shape, evidence in zip(shapes, recorded):
        original = {k:v for k,v in shape.items() if k not in {
            'source_shape_type','source_shape_index','source_body_index','source_body_identity',
            'source_reference_path','association_rule'}}
        if evidence.get('source_shape') != original:
            raise ValueError('Legacy receipt source shape differs')
        result[(shape['source_shape_type'],shape['source_shape_index'])] = 'physics_reference:'+shape['name'].lower()
    if len(set((kind,name) for (kind,_),name in result.items())) != len(result):
        raise ValueError('Legacy exporter label collision requires explicit provenance')
    return result
