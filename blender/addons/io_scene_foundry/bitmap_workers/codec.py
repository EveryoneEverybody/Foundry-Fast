"""Load the numerical subset of the bundled serial decoder without host imports."""
import ast
import builtins
import hashlib
import math
from pathlib import Path
import struct
import symtable

import numpy as np

METHODS = frozenset('''
_equirectangular_face_type _cubemap_equirectangular_coordinates _pad_cubemap_faces
_sample_cubemap_faces _cubemap_faces_to_equirectangular _rotate_cubemap_face
_cubemap_faces_from_vertical_rgba _cubemap_vertical_rgba_to_equirectangular
_expand_bits _expand_bit_value _decode_rgb565 _lerp_byte _decode_bc4_palette
_byte_to_sbyte _sbyte_to_normal_byte _decode_bc4_signed_palette _decode_dxn_z
_decode_dxt1_bitmap_rgba _decode_dxt3_bitmap_rgba _channel_values_to_rgba
_decode_dxt3a_values _decode_dxt5a_values _decode_dxt3a_bitmap_rgba
_decode_dxt5a_bitmap_rgba _decode_ctx1_bitmap_rgba _decode_bc5_unsigned_channels
_decode_dxn_mono_alpha_bitmap_rgba _decode_dxt5_bitmap_rgba _decode_dxn_bitmap_rgba
_decode_uncompressed_bitmap_rgba _decode_bitmap_rgba _linear_to_srgb
_convert_xrgb_rgba_to_srgb _tiff_entry _write_rgba_tiff
'''.split())
BUILTINS = frozenset('''
staticmethod classmethod bytes bytearray int float tuple list dict str range len
min max round enumerate zip isinstance ValueError open
'''.split())
PREFIXES = ('BITMAP_FORMAT_', 'UNCOMPRESSED_BITMAP_', 'COMPRESSED_BITMAP_')


def load_codec(source_path=None):
    """Compile only allowlisted constants and static/class numerical methods."""
    path = Path(source_path) if source_path else Path(__file__).parents[1] / 'managed_blam/bitmap.py'
    source = path.read_bytes()
    tree = ast.parse(source, filename=str(path))
    constants = []
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and t.id.startswith(PREFIXES)
                                                for t in node.targets):
            constants.append(node)
            names.update(t.id for t in node.targets)
    tag = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'BitmapTag')
    methods = [node for node in tag.body if isinstance(node, ast.FunctionDef) and node.name in METHODS]
    if {node.name for node in methods} != METHODS:
        raise ValueError('Bundled bitmap codec method set changed')
    allowed = names | BUILTINS | {'BitmapTag', 'np', 'math', 'struct'}
    for node in methods:
        if len(node.decorator_list) != 1 or not isinstance(node.decorator_list[0], ast.Name) or node.decorator_list[0].id not in {'staticmethod', 'classmethod'}:
            raise ValueError(f'Host-bound bitmap method: {node.name}')
        if any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(node)):
            raise ValueError(f'Import in bitmap worker method: {node.name}')
    module = ast.Module(body=constants + [ast.ClassDef(name='BitmapTag', bases=[], keywords=[],
                                                       body=methods, decorator_list=[])], type_ignores=[])
    ast.fix_missing_locations(module)
    text = ast.unparse(module)
    symbols = symtable.symtable(text, str(path), 'exec')
    def check(table):
        for symbol in table.get_symbols():
            if symbol.is_referenced() and symbol.is_global() and symbol.get_name() not in allowed:
                raise ValueError(f'Host dependency in bitmap worker: {symbol.get_name()}')
        for child in table.get_children():
            check(child)
    check(symbols)
    # The original codec remains the single source. No Tag class or add-on import executes.
    namespace = {'__builtins__': {name: getattr(builtins, name) for name in BUILTINS} |
                 {'__build_class__': builtins.__build_class__},
                 '__name__': 'detached_bitmap_codec', 'np': np, 'math': math, 'struct': struct}
    exec(compile(module, str(path), 'exec'), namespace)
    return namespace['BitmapTag'], hashlib.sha256(text.encode()).hexdigest()
