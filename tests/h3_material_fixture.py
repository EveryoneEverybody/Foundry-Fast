"""Synthetic H3 material records."""
def manifest():
    return {
        'format': 'foundry.h3-shaders', 'version': 1,
        'source_tag': 'objects/test/test.model', 'source_game': 'halo3_mcc',
        'shaders': {'objects/test/test.shader': {
            'source': 'objects/test/test.shader', 'group': 'rmsh', 'status': 'resolved_snapshot',
            'categories': [{'category': 'albedo', 'option': 'default'},
                           {'category': 'bump_mapping', 'option': 'standard'},
                           {'category': 'blend_mode', 'option': 'opaque'}],
            'parameters': [
                {'name': name, 'type': 'bitmap', 'bitmap': 'objects/test/image#0',
                 'transform': [2.0, 3.0, .25, -.5],
                 'sampler': {'filter': 'linear', 'address_x': 'wrap', 'address_y': 'wrap'}}
                for name in ('base_map', 'detail_map', 'bump_map', 'alpha_test_map',
                             'change_color_map', 'detail_map2', 'self_illum_map')
            ] + [{'name': 'albedo_color', 'type': 'color', 'value': [.2, .4, .8, 1]}],
            'diagnostics': []}},
        'bitmaps': {'objects/test/image#0': {
            'path': 'objects/test/image', 'index': 0, 'width': 2, 'height': 2, 'depth': 1,
            'type': '2D texture', 'format': 'a8r8g8b8', 'curve': 'Srgb',
            'preview': 'textures/00000.tif', 'status': 'preview'}}}
