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


def lighting_count_errors(source, native):
    """Reject missing authored lights before Faux; this is not visual parity."""
    errors = []
    for key in ('sky_samples', 'light_definitions', 'light_instances'):
        if native[key] != source[key]:
            errors.append(f"Native {key} count {native[key]} differs from source {source[key]}")
    # Tool may split/merge material rows; their indices/counts are not portable.
    # A later surface mapping validates row contents. A zero result here must
    # never be allowed to hide meaningful source emission.
    if source['emissive_rows'] and not native['emissive_rows']:
        errors.append('Source emission exists but native lighting info has no emissive rows')
    if source['sky_samples'] and (not math.isfinite(native['sky_energy']) or native['sky_energy'] <= 0):
        errors.append('Native sky samples contain no finite positive lighting energy')
    return errors
