"""Reach generic-light authoring distances, separate from surface emission.

Semantic plans and positions use world units. Reach's native light-definition
load postprocess divides attenuation authoring distances by 100. Match the
ordinary Reach light exporter at the writer boundary, exactly once.
"""
import math

REACH_ATTENUATION_AUTHORING_SCALE = 100.0


def reach_attenuation_units(world_distance):
    value = float(world_distance) * REACH_ATTENUATION_AUTHORING_SCALE
    if not math.isfinite(value) or abs(value) > 3.402823466e38:
        raise ValueError('Generic-light attenuation must fit a finite float32')
    return value


def attenuation_record(definition):
    source = {k: list(definition[k]) for k in ('near_attenuation', 'far_attenuation')}
    if any(len(v) != 2 for v in source.values()):
        raise ValueError('Generic-light attenuation requires two bounds')
    authored = {k: [reach_attenuation_units(x) for x in v] for k, v in source.items()}
    return dict(SOURCE_WORLD_UNITS=source, REACH_AUTHORING_UNITS=authored,
                EXPECTED_FAUX_WORLD_UNITS=source)
