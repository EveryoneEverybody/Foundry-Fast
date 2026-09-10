"""Read an H3 Tool scenario export into the shared complete-scenario IR."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import fixtures, scenario_ir
from port_environment.paths import atomic_json, digest, relative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xml', required=True)
    parser.add_argument('--tags-root', required=True)
    parser.add_argument('--scenario', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--initial-zone')
    parser.add_argument('--spawn-flag')
    args = parser.parse_args()
    source = relative(args.scenario).as_posix()
    root = Path(args.tags_root).resolve(strict=True)
    tag = (root/source).resolve(strict=True)
    if not tag.is_relative_to(root):
        raise ValueError('Source escapes tags root')
    output = Path(args.output).resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError('Inventory output must be new and outside the source tags')
    xml = fixtures.read_authoring(args.xml, scenario_ir.FIELDS)
    selection = scenario_ir.select_all(xml, source, args.initial_zone, args.spawn_flag)
    report = scenario_ir.inventory(xml, selection, scenario_ir.top_level_counts(args.xml),
                                  source_sha256=digest(tag), xml_sha256=digest(args.xml))
    output.mkdir(parents=True)
    atomic_json(output/'scenario-inventory.json', report)
    atomic_json(output/'scenario-structure.json', selection)
    print(json.dumps(dict(bsps=len(selection['bsps']), designs=sum(bool(b['structure_design']) for b in selection['bsps']),
        zones=len(selection['zone_sets']), object_names=len(report['object_names']),
        device_groups=len(report['device_groups']), device_relationships=len(report['device_relationships']),
        families={k:dict(palette=v['source_palette_count'], placements=v['source_instance_count']) for k,v in report['families'].items()}), indent=2))


if __name__ == '__main__':
    main()
