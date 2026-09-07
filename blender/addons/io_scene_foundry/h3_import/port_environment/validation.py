"""Conservative diagnostics at the official target Tool boundary."""
import re
import math

NATIVE_TAG_EXTENSIONS = {'.scenario', '.scenario_structure_bsp', '.scenario_structure_lighting_info',
    '.structure_design', '.structure_seams', '.scenery', '.model', '.render_model', '.shader', '.bitmap',
    '.scenario_lightmap', '.scenario_lightmap_bsp_data'}


def geometry_errors(log):
    result = []
    for line in log.splitlines():
        if (re.search(r'\((structure_bsp|render_model)\b.*\)', line, re.I)
                and re.search(r'open edge:|degenerate triangle|duplicate face|overlapping surface|error:', line, re.I)):
            result.append(line.strip())
        elif re.search(r'###\s*ERROR|FATAL ERROR|IMPORT FAILED', line):
            result.append(line.strip())
    return result


def lighting_evidence(logs):
    text = '\n'.join(logs)
    errors = [line.strip() for line in text.splitlines()
              if re.search(r'LIGHTMAPPER FAILED|FATAL ERROR|TASK FAILED', line)]
    energies = [float(value) for value in re.findall(r'(?:DC|Linear|Quad):[^\s%]+%of([0-9.Ee+\-]+)', text)]
    if not energies or any(not math.isfinite(v) for v in energies) or max(energies) <= 0:
        errors.append('Faux did not report finite, nonzero VMF lighting energy')
    return dict(errors=errors, vmf_energy_statistics=energies)
