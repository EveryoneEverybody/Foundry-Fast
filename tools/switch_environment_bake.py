"""Select a captured, hash-pinned baseline/diagnostic lighting state."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.bake_switch import switch

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--variant', required=True, choices=('baseline','scale10'))
    parser.add_argument('--dry-run', action='store_true')
    args=parser.parse_args()
    print(json.dumps(switch(json.loads(Path(args.receipt).read_text(encoding='utf-8-sig')), args.variant, dry_run=args.dry_run), indent=2))
