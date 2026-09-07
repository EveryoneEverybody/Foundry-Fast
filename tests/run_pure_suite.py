"""Run every pure test module in isolation; some legacy fixtures install bpy stubs."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
failures = []
for path in sorted((root / 'tests').glob('test_*.py')):
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', path.name],
                            cwd=root, capture_output=True, text=True)
    print(f'{path.name}: {"PASS" if result.returncode == 0 else "FAIL"}', flush=True)
    if result.returncode:
        failures.append(path.name)
        print(result.stdout + result.stderr, flush=True)
if failures:
    raise SystemExit('Failed: ' + ', '.join(failures))
print('All pure test modules passed in separate processes', flush=True)
