"""Validate the Rust-produced stress inventory through the production Python reader."""
import importlib
from pathlib import Path
import sys
from types import ModuleType

root = Path(__file__).resolve().parents[1]
package = ModuleType("h3_stress")
package.__path__ = [str(root / "blender/addons/io_scene_foundry/h3_import")]
sys.modules[package.__name__] = package
inspection = importlib.import_module("h3_stress.scenario_inspection")
data = inspection.load(Path(sys.argv[1]) / "scenario.h3inspect.json")
assert data["record_count"] == 2_000_001
assert "records" not in data
count = 0
for row in inspection.iter_records(data):
    assert row["value"] == count
    count += 1
assert count == 2_000_001
assert not list(inspection.iter_records(data, roots={"zones"}))
print(f"Cross-language scenario stress test passed: {count} records, {len(data['chunks'])} bounded chunks")
