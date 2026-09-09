"""Immutable H3 semantics -> explicit Reach plans. No Blender, I/O or tag writes.

Equations: h3_reach_rmsh_translation_spec_v1_2026-09-09.md. These are
directional engine migrations, not an assertion of identical H3/Reach BRDFs.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from types import MappingProxyType

TRANSLATED = 'TRANSLATED'
UNRESOLVED = 'UNRESOLVED_REQUIRES_RULE'
SINGLE = 'h3.single_lobe_phong_to_reach.two_lobe_phong.v1'
TWO = 'h3.two_lobe_phong_to_reach.two_lobe_phong.canonical_v1'
RULES = {'single_lobe_phong': SINGLE, 'two_lobe_phong': TWO,
         'diffuse_only': 'h3.diffuse_only_to_reach.diffuse_only.v1',
         'none': 'h3.none_to_reach.none.v1'}


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in sorted(value.items())})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Nonfinite material value')
        return value
    raise TypeError('Material contracts contain JSON values only')


def thaw(value):
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw(v) for v in value]
    return value


def canonical_json(value):
    return json.dumps(thaw(value), sort_keys=True, separators=(',', ':'), allow_nan=False)


def _named(rows, key):
    result = {}
    for row in rows:
        name = row[key]
        if name in result:
            raise ValueError('Duplicate material field: ' + name)
        result[name] = row
    return result


def function_state(parameter, functions):
    if parameter.get('extern'):
        return 'EXTERN'
    if not functions:
        return 'UNKNOWN_FUNCTION' if parameter.get('has_functions') else 'STATIC'
    for f in functions:
        if f.get('input', f.get('input_name')) or f.get('range', f.get('range_name')):
            return 'INPUT_DRIVEN_FUNCTION'
        try:
            data = bytes.fromhex(f.get('function_hex', f.get('function_data_hex')) or '')
        except ValueError:
            return 'UNKNOWN_FUNCTION'
        # Same constant/value header contract as port_environment.semantics;
        # ranged, unknown, periodic and time-varying functions stay unresolved.
        if len(data) < 32 or data[0] > 10 or data[1] & ~63 or data[2] > 4:
            return 'UNKNOWN_FUNCTION'
        if data[0] != 1 or data[1] & 1:
            return 'NONCONSTANT_FUNCTION'
    return 'CONSTANT_FUNCTION'


@dataclass(frozen=True)
class H3MaterialRecord:
    source_shader: str
    source_group: str
    definition: str | None
    categories: tuple
    parameters: Mapping
    bitmaps: Mapping
    provenance: Mapping
    raw_record: Mapping
    identity: str

    def __post_init__(self):
        for name in ('categories', 'parameters', 'bitmaps', 'provenance', 'raw_record'):
            object.__setattr__(self, name, freeze(getattr(self, name)))

    @classmethod
    def from_resolved(cls, record, bitmaps=None, provenance=None):
        """Detach the decoder record, retaining defaults, bytes and unknown metadata."""
        raw = freeze(record)
        categories = tuple(raw.get('categories', ()))
        _named(categories, 'category')
        description = raw.get('source_description', {})
        # Source tags can contain duplicate authored entries. The existing
        # resolver owns effective-value precedence; retain all function bytes
        # for classification instead of re-resolving or losing either entry.
        authored = {}
        described = {}
        for row in raw.get('authored_parameters', ()):
            authored.setdefault(row['name'], []).extend(row.get('functions', ()))
        for row in description.get('source_parameters', ()):
            described.setdefault(row['name'], []).extend(row.get('animations', ()))
        parameters = {}
        for name, p in _named(raw.get('parameters', ()), 'name').items():
            functions = authored.get(name)
            if functions is None:
                functions = described.get(name, p.get('functions', ()))
            parameters[name] = dict(p, functions=functions,
                                    function_state=function_state(p, functions))
        referenced = {p['bitmap'] for p in parameters.values() if p.get('bitmap')}
        bitmap_records = {k: v for k, v in (bitmaps or {}).items() if k in referenced}
        identity = sha256(canonical_json(dict(record=raw, bitmaps=bitmap_records,
                                             provenance=provenance or {})).encode()).hexdigest()
        return cls(raw['source'], raw.get('group', ''),
                   raw.get('definition', description.get('definition')), categories,
                   freeze(parameters), freeze(bitmap_records), freeze(provenance or {}), raw, identity)

    @property
    def options(self):
        return {c['category']: c['option'] for c in self.categories}

    @property
    def material_model(self):
        return self.options.get('material_model')


@dataclass(frozen=True)
class ReachAuthoringPlan:
    """Frozen JSON contract; compatibility inputs never masquerade as sockets."""
    payload: Mapping

    def __post_init__(self):
        object.__setattr__(self, 'payload', freeze(self.payload))

    def to_dict(self):
        return thaw(self.payload)

    @property
    def status(self):
        return self.payload['translation_status']

    @property
    def rule_id(self):
        return self.payload['rule_id']

    def semantic_values(self):
        result = {'material_model': self.payload['options'].get('material_model')}
        for lane in ('parameters', 'compatibility_inputs'):
            result.update({k: thaw(v.get('value')) for k, v in self.payload[lane].items()})
        return result


def _real(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Expected a finite scalar')
    return value


def power_to_roughness(power):
    return min(1.0, max(0.0, 0.553772986 * min(2000.0, max(0.01, _real(power))) ** -0.4551))


def roughness_to_compatibility_power(roughness):
    return max(0.0, 0.272909999 * max(0.01, _real(roughness)) ** -1.3973)


# Bounded ordinary-rmsh lanes already carried by the importer. Deliberately
# enumerated, not a same-name fallback for arbitrary source categories/options.
DIRECT_OPTIONS = {
    'albedo': {'default', 'constant_color', 'detail_blend', 'two_detail',
               'two_detail_overlay', 'three_detail_blend', 'two_change_color'},
    'bump_mapping': {'off', 'standard', 'detail'},
    'alpha_test': {'none', 'simple'},
    'specular_mask': {'no_specular_mask', 'specular_mask_from_diffuse',
                      'specular_mask_mult_diffuse', 'specular_mask_from_texture'},
    'environment_mapping': {'none', 'per_pixel', 'dynamic'},
    'self_illumination': {'off', 'simple', 'simple_with_alpha_mask', 'illum_detail'},
    'blend_mode': {'opaque', 'additive', 'alpha_blend'},
    'parallax': {'off', 'simple', 'interpolated'},
}
DIRECT_PARAMETERS = frozenset('''albedo_color base_map detail_map detail_map2 detail_map3
detail_map_overlay bump_map bump_detail_map alpha_test_map specular_mask_texture
diffuse_coefficient env_tint_color environment_map height_map height_scale no_dynamic_lights
self_illum_color self_illum_intensity self_illum_map self_illum_detail_map
change_color_map primary_change_color secondary_change_color'''.split())
SPECULAR_INPUTS = frozenset('''specular_coefficient analytical_specular_contribution
area_specular_contribution environment_map_specular_contribution roughness analytical_roughness
normal_specular_power glancing_specular_power normal_specular_tint glancing_specular_tint
fresnel_curve_steepness albedo_specular_tint_blend specular_tint env_roughness_scale
env_roughness_offset analytical_anti_shadow_control order3_area_specular'''.split())
COMMON_LEGACY = frozenset('''specular_coefficient analytical_specular_contribution
area_specular_contribution environment_map_specular_contribution env_roughness_scale
analytical_anti_shadow_control order3_area_specular'''.split())
MODEL_INPUTS = {
    'single_lobe_phong': COMMON_LEGACY | {'roughness', 'specular_tint'},
    'two_lobe_phong': COMMON_LEGACY | {'normal_specular_power', 'glancing_specular_power',
        'normal_specular_tint', 'glancing_specular_tint', 'fresnel_curve_steepness', 'albedo_specular_tint_blend'},
}


def translate(source):
    if not isinstance(source, H3MaterialRecord):
        raise TypeError('Translation requires an immutable H3MaterialRecord')
    model = source.material_model
    rule = RULES.get(model) if source.source_group == 'rmsh' and source.source_shader.lower().endswith('.shader') else None
    plan = dict(format='foundry.h3-reach-material-plan', version=1,
                source_shader=source.source_shader, source_identity=source.identity,
                source_record_sha256=sha256(canonical_json(source.raw_record).encode()).hexdigest(),
                rule_id=rule, rule_version=1 if rule else None,
                target_node='foundry_reach.shader' if rule else None,
                destination_group='rmsh' if rule else None, options={}, parameters={},
                field_origins={}, compatibility_inputs={}, diagnostics=[],
                function_extern_status={k: p['function_state'] for k, p in source.parameters.items()},
                translation_status=TRANSLATED, brdf_status=TRANSLATED if rule else UNRESOLVED)

    def unresolved(field, reason):
        plan['translation_status'] = UNRESOLVED
        plan['diagnostics'].append(dict(field=field, status=UNRESOLVED, reason=reason))
        plan['field_origins'][field] = dict(origin='UNRESOLVED', source_fields=[field])

    def put(name, value, origin, fields=(), kind='real', lane='parameters', metadata=None):
        row = dict(metadata or {}, name=name, type=kind, value=value, origin=origin)
        row.pop('functions', None)
        row.pop('function_state', None)
        row['has_functions'] = False
        plan[lane][name] = row
        plan['field_origins'][name] = dict(origin=origin, source_fields=list(fields))

    if not rule:
        unresolved('material_model', f'No proven ordinary-rmsh rule for {source.source_group}/{model}')
        return ReachAuthoringPlan(plan)
    plan['options']['material_model'] = 'two_lobe_phong' if model in {'single_lobe_phong', 'two_lobe_phong'} else model
    plan['field_origins']['material_model'] = dict(origin='H3_TRANSFORM' if model == 'single_lobe_phong' else 'H3_DIRECT', source_fields=['material_model'])
    # Reach-only category zero selections from ShaderTag's Wetness and
    # AlphaBlendSource enums. Explicitly mark target defaults as derived.
    for name, value in (('wetness', 'default'), ('alpha_blend_source', 'from_albedo_alpha_without_fresnel')):
        plan['options'][name] = value
        plan['field_origins'][name] = dict(origin='REACH_DERIVED', source_fields=[],
            evidence='Reach ShaderTag category enum default')
    if source.raw_record.get('status') != 'resolved_snapshot':
        unresolved('source', 'A resolved H3 snapshot is required')
    for category, option in sorted(source.options.items()):
        if category == 'material_model':
            continue
        if category == 'misc' and option == 'first_person_never':
            # Existing native option readback maps this source default to Reach default.
            plan['options']['misc'] = 'default'
        elif category in {'distortion', 'soft_fade', 'misc_attr_animation'} and option == 'off':
            plan['field_origins'][category] = dict(origin='H3_DIRECT', source_fields=[category], disposition='disabled_source_feature')
            continue
        elif option in DIRECT_OPTIONS.get(category, ()):
            plan['options'][category] = option
        else:
            unresolved(category, 'No proven category rule: ' + option)
            continue
        plan['field_origins'][category] = dict(origin='H3_DIRECT', source_fields=[category])

    for name, p in source.parameters.items():
        state = p['function_state']
        if state == 'EXTERN':
            providers = {'dynamic_environment_map_0': 'dynamic environment map 1',
                         'dynamic_environment_map_1': 'dynamic environment map 2'}
            colors = {'primary_change_color': 'change color primary',
                      'secondary_change_color': 'change color secondary'}
            proven = ((source.options.get('environment_mapping') == 'dynamic' and providers.get(name) == p['extern']) or
                      (source.options.get('albedo') == 'two_change_color' and colors.get(name) == p['extern']))
            if proven and not p['functions']:
                put(name, None, 'REACH_DERIVED', [name], 'extern', 'compatibility_inputs',
                    dict(provider='Reach renderer', extern=p['extern']))
            else:
                unresolved(name, 'No proven runtime extern provider')
            continue
        if state not in {'STATIC', 'CONSTANT_FUNCTION'}:
            unresolved(name, state + ': source function retained; snapshot is not static authoring')
            if name in SPECULAR_INPUTS:
                plan['brdf_status'] = UNRESOLVED
            continue
        if name in SPECULAR_INPUTS:
            if model in {'diffuse_only', 'none'}:
                plan['field_origins'][name] = dict(origin='H3_DIRECT', source_fields=[name], disposition='not_declared_by_target_material_model')
            elif name not in MODEL_INPUTS[model]:
                unresolved(name, 'Unexpected parameter in this legacy material-model contract')
            continue
        if name == 'bump_detail_coefficient' and p.get('value') == 1:
            plan['field_origins'][name] = dict(origin='REACH_DERIVED', source_fields=[name], disposition='Reach detail normal has unit coefficient; native_contracts.unexposed_parameter')
        elif name in DIRECT_PARAMETERS:
            put(name, p.get('value'), 'H3_DIRECT', [name], p['type'], metadata=thaw(p))
        else:
            unresolved(name, 'No proven parameter rule')

    def scalar(name):
        p = source.parameters.get(name)
        if p is None or p['function_state'] not in {'STATIC', 'CONSTANT_FUNCTION'}:
            raise ValueError('Missing static effective source value: ' + name)
        return _real(p.get('value'))

    def color(name):
        p = source.parameters.get(name)
        if p is None or p['function_state'] not in {'STATIC', 'CONSTANT_FUNCTION'}:
            raise ValueError('Missing static effective source color: ' + name)
        values = p.get('value')
        if not isinstance(values, tuple) or len(values) != 4:
            raise ValueError('Expected four source color components: ' + name)
        return [_real(v) for v in values]

    if model in {'single_lobe_phong', 'two_lobe_phong'}:
        try:
            sc = scalar('specular_coefficient')
            roughness = scalar('roughness') if model == 'single_lobe_phong' else power_to_roughness(scalar('normal_specular_power'))
            asc = scalar('analytical_specular_contribution')
            if model == 'single_lobe_phong':
                asc *= roughness ** 4 * math.pi ** 2
                tint = color('specular_tint')
                angle = dict(color0_normal=tint, color1_glancing=tint, exponent=1.0)
                # Equal endpoints make the chosen constant exponent irrelevant.
                angle_fields = ['specular_tint']
                put('albedo_specular_tint_blend', 0.0, 'SYNTHESIZED')
            else:
                angle_fields = ['normal_specular_tint', 'glancing_specular_tint', 'fresnel_curve_steepness']
                angle = dict(color0_normal=color(angle_fields[0]), color1_glancing=color(angle_fields[1]), exponent=scalar(angle_fields[2]))
                put('glancing_roughness', power_to_roughness(scalar('glancing_specular_power')),
                    'H3_TRANSFORM', ['glancing_specular_power'], lane='compatibility_inputs')
                put('albedo_specular_tint_blend', scalar('albedo_specular_tint_blend'), 'H3_DIRECT', ['albedo_specular_tint_blend'])
            put('roughness', roughness, 'H3_DIRECT' if model == 'single_lobe_phong' else 'H3_TRANSFORM',
                ['roughness' if model == 'single_lobe_phong' else 'normal_specular_power'])
            put('specular_color_by_angle', angle, 'H3_REPACK', angle_fields, 'angle_color')
            put('specular_coefficient', 1.0, 'H3_TRANSFORM', ['specular_coefficient'])
            put('analytical_specular_contribution', asc * sc, 'H3_TRANSFORM',
                ['analytical_specular_contribution', 'specular_coefficient'] + (['roughness'] if model == 'single_lobe_phong' else []))
            put('area_specular_contribution', scalar('area_specular_contribution') * sc / math.pi,
                'H3_TRANSFORM', ['area_specular_contribution', 'specular_coefficient'])
            put('environment_map_specular_contribution', scalar('environment_map_specular_contribution') * sc,
                'H3_TRANSFORM', ['environment_map_specular_contribution', 'specular_coefficient'])
            put('analytical_roughness', roughness, 'SYNTHESIZED', ['roughness'])
            if 'env_roughness_scale' in source.parameters and source.parameters['env_roughness_scale'].get('value') is not None:
                scale = scalar('env_roughness_scale')
                put('env_roughness_scale', scale, 'H3_DIRECT', ['env_roughness_scale'])
                put('env_roughness_offset', 0.5 + 0.5 * roughness * (scale - 1), 'H3_TRANSFORM', ['roughness', 'env_roughness_scale'])
            for name in ('order3_area_specular', 'analytical_anti_shadow_control'):
                if name in source.parameters:
                    if name == 'order3_area_specular' and source.parameters[name].get('value') is False:
                        plan['field_origins'][name] = dict(origin='H3_DIRECT', source_fields=[name], disposition='disabled_optional_path')
                    else:
                        unresolved(name, 'No exact Reach rule for this legacy control')
        except (ValueError, OverflowError) as exc:
            plan['brdf_status'] = UNRESOLVED
            unresolved('material_model', str(exc))
    # A nonfinite derived value must not escape as a successful plan.
    try:
        return ReachAuthoringPlan(plan)
    except ValueError:
        plan['parameters'].clear()
        plan['compatibility_inputs'].clear()
        plan['brdf_status'] = UNRESOLVED
        unresolved('material_model', 'Nonfinite migration result')
        return ReachAuthoringPlan(plan)
