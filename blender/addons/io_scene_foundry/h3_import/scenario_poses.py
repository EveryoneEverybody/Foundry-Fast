"""Validate packed scenario pose records without inventing their missing codec.

H3 source definition has a node count, signed byte bit vector and signed short
stream. Real 040_voi includes 63-, 103- and 105-short records, so treating the
whole stream as short4 quaternions (or silently truncating it) loses source data.
"""


def validate_stored_pose(records, payload):
    def fallback(reason): return dict(status='rest_pose', reason='Stored pose: ' + reason)
    if not records: return dict(status='empty')
    if len(records) != 1: return fallback(f'{len(records)} pose blocks; block selection is unsupported')
    pose = records[0]
    count, mask, values = pose['node_count'], pose['bit_vector'], pose['orientations']
    if type(count) is not int or count < 0 or count > 255:
        return fallback('invalid source node count')
    if any(type(v) is not int or not -128 <= v <= 127 for v in mask):
        return fallback('invalid signed-byte bit vector')
    if any(type(v) is not int or not -32768 <= v <= 32767 for v in values):
        return fallback('invalid signed-short orientation stream')
    if count == 0 and not values and not any(mask): return dict(status='empty')
    if payload is None: return fallback('model hierarchy unavailable')
    model_count = len(payload['render']['nodes'])
    if count != model_count: return fallback(f'node-count mismatch: source {count}, model {model_count}; pose not applied')
    if len(mask)*8 < count: return fallback('bit vector is shorter than the source hierarchy')
    return fallback(f'{count} nodes, {len(mask)} mask bytes, {len(values)} packed shorts; H3 rotation/translation codec and hierarchy correspondence require verification; source stream retained exactly')
