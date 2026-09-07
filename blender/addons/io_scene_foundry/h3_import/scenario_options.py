"""Source classification and standard Foundry scenario options (no bpy or tag writes)."""
from dataclasses import dataclass
from pathlib import Path

from .core import resolve_tags_root


def classify_source(source, reach_root, configured_h3=None):
    source = Path(source).resolve(strict=True)
    reach = Path(reach_root).resolve()
    if source.suffix.lower() != '.scenario' or not source.is_file():
        raise ValueError('Expected a loose .scenario file')
    h3 = None
    if configured_h3:
        configured = Path(configured_h3).resolve()
        # A configured kit directory is equivalent to its tags child.
        h3 = configured / 'tags' if (configured / 'tags').is_dir() else configured
    else:
        h3 = next((p for p in source.parents if p.name.lower() == 'tags'
                   and p.parent.name.lower() == 'h3ek'), None)
    is_reach = source.is_relative_to(reach)
    is_h3 = h3 is not None and source.is_relative_to(h3.resolve())
    if is_reach and is_h3:
        raise ValueError('Ambiguous scenario source: Reach and H3 tags roots overlap')
    if is_reach:
        return 'reach', reach
    if is_h3:
        return 'halo3', resolve_tags_root(source, h3)
    raise ValueError('Unknown scenario source. Select a file under the active Reach tags root or configure H3EK tags in Foundry preferences')


INSPECTION_PROPERTIES = {
    'h3_inspect_ai': 'AI Organization',
    'h3_inspect_firing_positions': 'Firing Positions',
    'h3_inspect_giant_hints': 'Giant Hints',
    'h3_inspect_script_points': 'Script Points',
    'h3_inspect_reference_debug': 'Trigger and Reference Debug Data',
    'h3_inspect_sound': 'Sound References',
    'h3_inspect_lights': 'Light References',
    'h3_detailed_points': 'Individual Firing Position Objects',
}


@dataclass(frozen=True)
class ScenarioOptions:
    geometry: bool = True
    objects: bool = False
    materials: bool = False
    sky: str = ''
    render_only: bool = True
    lights: bool = True
    setup_as_asset: bool = False
    merge_structure: bool = True
    design: bool = False
    decals: bool = False
    decorators: bool = False
    always_extract_bitmaps: bool = False
    ai: bool = False
    firing_positions: bool = False
    giant_hints: bool = False
    script_points: bool = False
    reference_debug: bool = False
    sound: bool = False
    light_references: bool = False
    detailed_points: bool = False

    @classmethod
    def from_operator(cls, op):
        def flag(name): return bool(getattr(op, name, False))
        return cls(geometry=flag('tag_bsp_import_geometry'), objects=flag('tag_scenario_import_objects'),
            materials=flag('build_blender_materials'), sky=getattr(op, 'tag_sky', '') or '',
            render_only=flag('tag_bsp_render_only'), lights=flag('tag_import_lights'),
            setup_as_asset=flag('setup_as_asset'), merge_structure=not flag('tag_bsp_skip_structure_merge'),
            design=flag('tag_import_design'), decals=flag('tag_scenario_import_decals'),
            decorators=flag('tag_scenario_import_decorators'), always_extract_bitmaps=flag('always_extract_bitmaps'),
            ai=flag('h3_inspect_ai'), firing_positions=flag('h3_inspect_firing_positions'),
            giant_hints=flag('h3_inspect_giant_hints'), script_points=flag('h3_inspect_script_points'),
            reference_debug=flag('h3_inspect_reference_debug'), sound=flag('h3_inspect_sound'),
            light_references=flag('h3_inspect_lights'), detailed_points=flag('h3_detailed_points'))

    def placement_enabled(self, category):
        if category == 'sound scenery': return self.sound
        if category == 'light volumes': return self.light_references
        return self.objects

    @property
    def content(self):
        return self.objects or self.ai or self.reference_debug or self.sound or self.light_references

    @property
    def hints(self):
        return self.giant_hints or self.firing_positions or self.script_points
