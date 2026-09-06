"""Reject unsupported static definitions before any Blender construction starts."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

PATH = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry/scenario_static_direct.py'
NAMES = {'DirectStaticUnsupported', '_allowed_pair', '_rigid_selection', 'build_rigid_render'}
TREE = ast.parse(PATH.read_text())
MODULE = ast.Module(body=[n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                         and n.name in NAMES], type_ignores=[])
NAMESPACE = {'Region': lambda element: element}
exec(compile(MODULE, str(PATH), 'exec'), NAMESPACE)
Unsupported = NAMESPACE['DirectStaticUnsupported']


class Elements(list):
    @property
    def Count(self):
        return len(self)


def block(values):
    return NS(Elements=Elements(values))


def permutation(name='base', index=0, count=1, clone=''):
    return NS(name=name, mesh_index=index, mesh_count=count, clone_name=clone)


def source(indices=(0, -1), perms=None, instances=False):
    meshes = [NS(SelectField=lambda field, value=value: NS(Data=value)) for value in indices]
    if perms is None:
        perms = [permutation(count=len(indices))]
    fields = {'Block:instance placements': block([None] if instances else []),
              'LongBlockIndex:instance mesh index': NS(Value=0 if instances else -1)}
    return NS(block_compression_info=block([None]),
              block_regions=block([NS(name='hull', permutations=perms)]),
              block_meshes=block(meshes), block_nodes=block([None, None]),
              tag=NS(SelectField=fields.__getitem__))


class PreflightTests(unittest.TestCase):
    def test_late_skinned_mesh_allocates_nothing(self):
        touched = []
        namespace = dict(NAMESPACE)
        for name in ('_read_nodes', '_node_world_matrices', 'CompressionBounds', 'Material', 'Mesh'):
            def forbidden(*args, _name=name, **kwargs):
                touched.append(_name)
                raise AssertionError(f'construction before validation: {_name}')
            namespace[name] = forbidden
        exec(compile(MODULE, str(PATH), 'exec'), namespace)
        with self.assertRaisesRegex(namespace['DirectStaticUnsupported'], 'skinned'):
            namespace['build_rigid_render'](source(), None, None, None)
        self.assertEqual(touched, [])

    def test_unselected_skinned_permutation_does_not_force_fallback(self):
        model = source(perms=[permutation('base', 0), permutation('destroyed', 1)])
        selected = NAMESPACE['_rigid_selection'](model, {('hull', 'base')})
        self.assertEqual([(r.name, p.name, i) for r, p, i in selected], [('hull', 'base', 0)])

    def test_selection_keeps_order_and_permutation_identity(self):
        model = source((0, 1), [permutation('base', 0, 2), permutation('damaged', 1)])
        selected = NAMESPACE['_rigid_selection'](model, None)
        self.assertEqual([(p.name, i) for _, p, i in selected],
                         [('base', 0), ('base', 1), ('damaged', 1)])

    def test_instance_geometry_keeps_live_fallback(self):
        with self.assertRaisesRegex(Unsupported, 'instance geometry'):
            NAMESPACE['_rigid_selection'](source((0,), instances=True), None)

    def test_clone_keeps_live_fallback(self):
        with self.assertRaisesRegex(Unsupported, 'material clones'):
            NAMESPACE['_rigid_selection'](source((0,), [permutation(clone='base')]), None)

    def test_invalid_mesh_and_bone_indices_fail_before_build(self):
        for model, reason in ((source((0,), [permutation(index=3)]), 'render mesh index'),
                              (source((3,)), 'rigid node index')):
            with self.subTest(reason=reason), self.assertRaisesRegex(Unsupported, reason):
                NAMESPACE['_rigid_selection'](model, None)

    def test_empty_selection_keeps_live_fallback(self):
        with self.assertRaisesRegex(Unsupported, 'no rigid geometry'):
            NAMESPACE['_rigid_selection'](source((0,)), {('hull', 'absent')})

    def test_missing_compression_keeps_live_fallback(self):
        model = source((0,)); model.block_compression_info = block([])
        with self.assertRaisesRegex(Unsupported, 'compression info'):
            NAMESPACE['_rigid_selection'](model, None)

    def test_functions_are_built_only_after_supported_geometry(self):
        build = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'try_build')
        calls = {name: [] for name in ('functions_to_blender', 'build_rigid_render')}
        for node in ast.walk(build):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, 'attr', '')
                if name in calls:
                    calls[name].append(node.lineno)
        self.assertEqual(len(calls['functions_to_blender']), 1)
        self.assertGreater(calls['functions_to_blender'][0], calls['build_rigid_render'][0])


if __name__ == '__main__':
    unittest.main()
