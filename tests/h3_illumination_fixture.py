"""Synthetic images with the fusion-coil illumination options and sampled values."""

SHADER = 'objects/test/illumination.shader'
MAP = 'objects/test/illum#0'
DETAIL = 'objects/test/illum_detail#0'


def manifest():
    categories = {'albedo': 'constant_color', 'bump_mapping': 'off', 'alpha_test': 'none',
                  'material_model': 'none', 'environment_mapping': 'none',
                  'self_illumination': 'illum_detail', 'blend_mode': 'additive'}
    parameters = [
        {'name': 'albedo_color', 'type': 'argb color', 'value': [1, 1, 1, 1]},
        {'name': 'self_illum_color', 'type': 'color', 'value': [1, 75 / 255, 0, 1], 'has_functions': True},
        {'name': 'self_illum_intensity', 'type': 'real', 'value': 3, 'has_functions': True},
    ]
    bitmaps = {}
    for name, key, scale, number in [('self_illum_map', MAP, 1, 0), ('self_illum_detail_map', DETAIL, 2, 1)]:
        parameters.append({'name': name, 'type': 'bitmap', 'bitmap': key,
                           'transform': [scale, scale, 0, 0], 'has_functions': scale == 2,
                           'sampler': {'filter': 'bilinear', 'address_x': 'wrap', 'address_y': 'wrap'}})
        bitmaps[key] = {'path': key.split('#')[0], 'index': 0, 'width': 4, 'height': 4,
                        'type': '2D texture', 'depth': 1, 'curve': 'Linear',
                        'preview': f'textures/{number:05}.tif'}
    return {'format': 'foundry.h3-shaders', 'version': 1, 'source_game': 'halo3_mcc',
            'source_tag': 'objects/test/illumination.model', 'bitmaps': bitmaps,
            'shaders': {SHADER: {'source': SHADER, 'group': 'rmsh', 'status': 'resolved_snapshot',
                                'categories': [{'category': c, 'option': o} for c, o in categories.items()],
                                'parameters': parameters, 'authored_parameters': [{'retained': 'source data'}]}}}


def set_option(data, category, option):
    for row in data['shaders'][SHADER]['categories']:
        if row['category'] == category:
            row['option'] = option
            return
    data['shaders'][SHADER]['categories'].append({'category': category, 'option': option})
