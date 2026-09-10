"""Deterministic, explicitly approximate H3 angular-emission authoring adapter.

The H3 frustum weighting law is not claimed to be recovered. For the environment
MVP we choose a linear-in-solid-angle taper, then express its equivalent cone
through Foundry's native spread/focus contract. Source distance attenuation is
independent of angles, and source bake power/color are never reduced to zero.
"""
import math


def plan(source):
    names = ('emissive power', 'emissive focus', 'emissive quality', 'frustum blend',
             'frustum falloff angle', 'frustum cutoffoff angle',
             'attenuation falloff', 'attenuation cutoff')
    values = {n:float(source[n]) for n in names}
    if not all(math.isfinite(v) for v in values.values()):
        raise ValueError('Nonfinite emissive inputs')
    flags = int(source['flags'])
    if flags & ~1 or flags < 0:
        raise ValueError('Unmapped emissive material behavior flag')
    power, focus, quality, blend, inner, outer, falloff, cutoff = (values[n] for n in names)
    color = [float(c) for c in source['emissive color'].split(',')]
    if len(color) != 3 or not all(math.isfinite(c) and c >= 0 for c in color) or not any(color):
        raise ValueError('Invalid or zero emissive color')
    if (power <= 0 or quality <= 0 or not 0 <= focus <= 1 or not 0 <= blend <= 1
        or not 0 <= inner <= outer <= 90 or not 0 <= falloff <= cutoff):
        raise ValueError('Emissive inputs outside the reviewed angular/attenuation domain')
    # Proxy convention: frustum angles are cone half-angles around the source
    # face normal. A taper linear in cos(theta) has the same angular integral
    # as a unit cone whose boundary cosine is the mean of the two cosines.
    cosine_frustum = (math.cos(math.radians(inner))+math.cos(math.radians(outer)))/2
    cosine_basic = math.cos(math.pi*(1-focus)/2)
    cosine_effective = (1-blend)*cosine_basic + blend*cosine_frustum
    spread = 2*math.acos(max(-1.0,min(1.0,cosine_effective)))
    target_focus = 1-spread/math.pi
    return dict(source_material_info=dict(source), classification='SOURCE_DERIVED_ANGULAR_APPROXIMATION',
        model='solid_angle_equivalent_cone_v1',
        assumptions=['H3 frustum angles are treated as half-angles about the authored surface normal',
            'frustum blend weights the basic emission cone and a frustum with a linear-in-cosine falloff',
            'This proxy is an MVP authoring choice, not a recovered H3 or Reach photometric law'],
        formula=dict(frustum_boundary_cosine='(cos(falloff_angle) + cos(cutoff_angle)) / 2',
            basic_boundary_cosine='cos(pi * (1 - source_focus) / 2)',
            combined_boundary_cosine='(1 - frustum_blend) * basic + frustum_blend * frustum',
            spread_radians='2 * acos(combined_boundary_cosine)', native_focus='1 - spread_radians / pi'),
        angular_integral_proxy_steradians=2*math.pi*(1-cosine_effective),
        target=dict(emissive_power=power, emissive_color=color, emissive_quality=quality,
            native_emissive_focus=target_focus, foundry_emissive_spread_radians=spread,
            attenuation_enabled=bool(flags & 1), attenuation_falloff_world=falloff, attenuation_cutoff_world=cutoff,
            emission_direction='Original material face normal; no invented light placement',
            power_policy='Keep source bake power under the existing native material unit conversion; do not re-normalize to an assumed photometric law',
            distance_policy='World-unit distances pass through the existing Foundry scene/attenuation unit adapter, independently of cone angles',
            writer_properties=dict(material_lighting_emissive_focus=spread),
            export_roundtrip='export/process.py and export/virtual_geometry.py: 1 - degrees(property) / 180',
            inverse_roundtrip='managed_blam/connected_geometry.py: radians(180 * (1 - tag_focus))'),
        fidelity_loss=['H3 frustum angular falloff, cutoff edge and blend curve are approximated by one native Reach focus lobe',
            'Exact photometric/angular normalization is unverified; source power, color and distance attenuation remain intact'],
        native_validation_required='Verify nonzero compiled emissive row power/color and native focus/attenuation before Faux')
