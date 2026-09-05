"""Synthetic time-overlay metadata, with a base distinct from the bind pose."""
import copy


def payload(nodes=None):
    if nodes is None:
        nodes = [{'name': 'hull', 'parent': -1, 'rest': {'position': [0, 0, 0], 'rotation': [1, 0, 0, 0], 'scale': 1}},
                 {'name': 'leg', 'parent': 0, 'rest': {'position': [1, 0, 0], 'rotation': [1, 0, 0, 0], 'scale': 1}}]
    nodes = copy.deepcopy(nodes)
    base_pose = [copy.deepcopy(n['rest']) for n in nodes]
    base_pose[0] = {'position': [4, 5, 6], 'rotation': [2**-0.5, 2**-0.5, 0, 0], 'scale': 2}
    reference = copy.deepcopy(base_pose)
    reference[1]['position'] = [9, 8, 7]
    flags = {prefix + component: [False]*len(nodes) for prefix in ('static_', 'animated_')
             for component in ('rotation', 'translation', 'scale')}
    flags['static_translation'][1] = True
    for component in ('rotation', 'translation', 'scale'):
        flags['animated_' + component][0] = True
    base = {'index': 8, 'name': 'combat:idle', 'animation_type': 'base', 'frame_info_type': 'none',
            'world_relative': False, 'source_node_count': len(nodes), 'source_frame_count': 149, 'status': 'not_selected'}
    clip = {'index': 5, 'name': 'combat:buckle_wobble', 'animation_type': 'overlay', 'frame_info_type': 'none',
            'world_relative': False, 'blend_screen': -1, 'object_space_parent_count': 0,
            'source_frame_count': 2, 'source_node_count': len(nodes), 'status': 'decoded',
            'decoded': {'kind': 'JMO', 'jma_file': 'clip_0005.jmo', 'motion_file': None,
                        'decoded_frame_count': 2, 'file_frame_count': 3, 'fps': 30,
                        'frame_layout': 'reference_then_codec_frames', 'movement_samples': [],
                        'overlay': {'composition': 'static_reference_then_parent_local_delta',
                                    'preview': 'composed_on_fixed_reference',
                                    'base': {'method': 'graph_action_candidate_first_frame', 'animation_index': 8,
                                             'animation_name': 'combat:idle', 'state': 'idle', 'frame': 0, 'graph_index': -1},
                                    'base_pose': base_pose, 'reference_pose': reference, 'node_flags': flags,
                                    'reference_frame': 1, 'first_sample_frame': 2}}}
    return {'format': 'foundry.h3-animation', 'version': 2, 'game': 'halo3_mcc', 'units': 'halo_world',
            'jma_units': 'halo_world_x100', 'quaternion_order': 'wxyz', 'rest_space': 'parent_local',
            'source_tag': 'objects/test/scarab.model', 'source_graph': 'objects/test/scarab.model_animation_graph',
            'nodes': nodes, 'animations': [clip, base]}
