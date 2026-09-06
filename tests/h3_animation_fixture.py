"""Synthetic animation data and metadata-only Scarab tag fixtures."""
import copy
import json
from pathlib import Path


def node(name, parent=-1, position=(0, 0, 0)):
    return {'name': name, 'parent': parent, 'rest': {'position': list(position), 'rotation': [1., 0., 0., 0.], 'scale': 1.}}


def payload():
    return {'format': 'foundry.h3-animation', 'version': 1, 'game': 'halo3_mcc',
            'units': 'halo_world', 'jma_units': 'halo_world_x100', 'quaternion_order': 'wxyz',
            'rest_space': 'parent_local', 'source_tag': 'objects/test/test.model',
            'source_graph': 'objects/test/test.model_animation_graph',
            'nodes': [node('hull', -1, (0, 0, 5)), node('leg', 0, (1, 0, 0))],
            'animations': [{'name': 'combat:move_front', 'index': 12, 'status': 'decoded',
                'source_node_count': 2, 'source_frame_count': 2, 'animation_type': 'base',
                'frame_info_type': 'dx,dy', 'world_relative': False,
                'decoded': {'kind': 'JMA', 'jma_file': 'clip_0012.jma', 'motion_file': 'motion_0012.jma',
                            'decoded_frame_count': 2, 'file_frame_count': 3, 'fps': 30,
                            'frame_layout': 'codec_frames_then_held_terminal'}}]}


def scarab_metadata():
    return json.loads((Path(__file__).parent / 'fixtures/scarab_animation_metadata.json').read_text())
