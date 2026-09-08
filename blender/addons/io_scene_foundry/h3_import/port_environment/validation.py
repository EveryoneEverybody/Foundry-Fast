"""Conservative diagnostics at the official target Tool boundary."""
import re
import math
from xml.parsers import expat


def native_xml_references(path,chunk_size=1024*1024):
    """Validate large Tool exports in bounded memory and collect reference labels.

    The small paired fixtures retain their separate 32 MiB limit. Real Faux
    lightprobe arrays can expand past a GiB of XML, mostly individual fields.
    """
    parser=expat.ParserCreate();references=set();root_seen=False
    def start(name,attributes):
        nonlocal root_seen
        if not root_seen:
            if name!='tag':raise ValueError('Expected a Tool/Foundation tag XML export')
            root_seen=True
        if name=='field' and attributes.get('type')=='tag reference':
            value=attributes.get('value','').split(',',1)[0].replace('\\','/')
            if value:references.add(value)
    def declaration(*args):raise ValueError('Unsupported XML entity or doctype declaration')
    parser.StartElementHandler=start
    parser.StartDoctypeDeclHandler=declaration
    parser.EntityDeclHandler=declaration
    def parse(content,final=False):
        # Same exact Tool sentinels as the paired-fixture parser, with complete
        # lines retained across chunks so substitutions cannot be split.
        content=content.replace(b',\xff\xff\xff\xff" type="tag reference"',b',NULL" type="tag reference"')
        content=content.replace(b'value="<unavailable>" type="pageable resource"',b'value="&lt;unavailable&gt;" type="pageable resource"')
        parser.Parse(content,final)
    with open(path,'rb') as stream:
        pending=b''
        while chunk:=stream.read(chunk_size):
            pending+=chunk
            end=pending.rfind(b'\n')+1
            if end:
                parse(pending[:end]);pending=pending[end:]
            if len(pending)>32*1024*1024:raise ValueError('Native XML field exceeds streaming record limit')
        parse(pending,True)
    if not root_seen:raise ValueError('Empty native XML')
    return references

NATIVE_TAG_EXTENSIONS = {'.scenario', '.scenario_structure_bsp', '.scenario_structure_lighting_info',
    '.structure_design', '.structure_seams', '.scenery', '.model', '.render_model', '.shader', '.shader_terrain', '.shader_foliage', '.bitmap',
    '.scenario_lightmap', '.scenario_lightmap_bsp_data', '.render_method_definition',
    '.render_method_template', '.pixel_shader', '.vertex_shader'}


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
