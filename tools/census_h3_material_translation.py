"""Inspect saved decoder/plan JSON without loading Blender, Tool or either kit."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType('h3_material_census_cli')
package.__path__ = [str(ROOT/'blender/addons/io_scene_foundry/h3_import')]
sys.modules[package.__name__] = package
module = importlib.import_module(package.__name__+'.material_census')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--plan', type=Path, help='Saved environment.plan.json selects the actual closure and usage')
    parser.add_argument('--rmop-contracts', type=Path, help='Read-only native RMOP declaration snapshot, keyed by canonical options JSON')
    parser.add_argument('--output', type=Path, required=True, help='New output directory; never overwritten')
    args = parser.parse_args()
    # Refuse output anywhere inside an editing-kit data/tags tree.
    resolved = args.output.resolve()
    if any(p.name.casefold() in {'tags', 'data'} for p in (resolved, *resolved.parents)):
        parser.error('Output must be outside tag/data trees')
    if resolved.exists():
        parser.error('Output directory already exists')
    inputs = {}
    def read(path):
        data = path.read_bytes()
        inputs[str(path.resolve())] = hashlib.sha256(data).hexdigest()
        return json.loads(data)
    report = module.census(read(args.manifest), read(args.plan) if args.plan else None,
                          destination_contracts=read(args.rmop_contracts) if args.rmop_contracts else None)
    report['input_sha256'] = inputs
    resolved.mkdir(parents=True, exist_ok=False)
    for name, data in (('materials.json', json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+'\n'),
                       ('materials.md', module.markdown(report))):
        with (resolved/name).open('x', encoding='utf-8') as stream:
            stream.write(data)
    print(json.dumps({k: report[k] for k in ('unique_materials', 'rule_counts', 'translation_status_counts', 'brdf_status_counts',
        'writer_status_counts', 'writer_eligible_by_model', 'unresolved_reason_counts', 'semantic_loss_counts', 'nonzero_semantic_loss_counts')}, indent=2))


if __name__ == '__main__':
    main()
