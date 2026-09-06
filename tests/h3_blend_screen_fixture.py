"""Synthetic nine-pose H3 aim screen; no game animation payload."""
import math
from h3_overlay_fixture import payload as time_overlay


def payload(nodes=None):
    manifest = time_overlay(nodes)
    manifest['version'] = 3
    clip = manifest['animations'][0]
    clip.update(index=1, name='combat:aim_still_up', blend_screen=0,
                source_frame_count=9, codec_frame_count=9)
    decoded = clip['decoded']
    decoded.update(jma_file='clip_0001.jmo', decoded_frame_count=9, file_frame_count=10,
                   frame_layout='reference_then_pose_samples')
    decoded['overlay']['preview'] = 'discrete_blend_screen_samples'
    decoded['blend_screen'] = {'index': 0, 'label': 'aim', 'layout': 'h3_aiming_screen',
        'angle_units': 'radians', 'counts': {side: 1 for side in ('right', 'left', 'down', 'up')},
        'angles': {side: math.pi / 4 for side in ('right', 'left', 'down', 'up')},
        'sample_count': 9, 'sample_order': 'source_codec_order', 'sample_coordinates': 'unresolved',
        'source_fields': {'struct': 'synthetic_aim_screen', 'raw_hex': '01000000'}}
    return manifest
