"""Synthetic bridge payload. No game assets."""
def payload():
    def node(name, parent, x):
        return {'name': name, 'parent': parent, 'position': [x, 200, 0], 'rotation': [1, 0, 0, 0]}
    def vertex(x, y, uv):
        return {'position': [x, y, 0], 'normal': [0, 0, 1], 'weights': [[1, 1.0]], 'uvs': [uv], 'color': None}
    render = {
        'nodes': [node('b_pedestal', -1, 100), node('b_panel', 0, 150)],
        'materials': [{'name': 'metal', 'label': '(1) default body'}, {'name': 'metal', 'label': '(2) alternate body'}],
        'markers': [{'name': 'attach', 'node': 1, 'position': [10, 0, 0], 'rotation': [1, 0, 0, 0], 'radius': 1}],
        'vertices': [vertex(150, 200, [0, 0]), vertex(170, 200, [1, 0]), vertex(150, 230, [0, 1]), vertex(150, 200, [0, 0])],
        'triangles': [{'material': 0, 'vertices': [0, 1, 2]}, {'material': 1, 'vertices': [3, 1, 2]}],
    }
    return {'format': 'foundry.h3-object', 'version': 1, 'units': 'jms_x100', 'game': 'halo3_mcc',
        'name': 'test_panel', 'source_tag': 'objects/test/panel.scenery', 'dependencies': {'render_model': 'objects/test/panel.render_model'},
        'shader_paths': ['objects/a/metal.shader', 'objects/b/metal.shader'], 'warnings': [], 'render': render,
        'collision': None, 'physics': {'shapes': [{'kind': 'box', 'name': 'panel', 'node': 1, 'material': 0,
            'position': [150, 200, 0], 'rotation': [1, 0, 0, 0], 'size': [20, 40, 60]}]}}
