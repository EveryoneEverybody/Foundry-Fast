"""Opt-in H3 two-lobe tint ordering for explicitly listed Reach shaders.

Run with a Python installation that can load the kit's ManagedBlam assembly.
Required: --reach-root, --dependencies (pythonnet), --output (new backup folder),
and one or more --shader paths relative to tags. No texture or scalar changes.
The installed candidate remains in place for manual evaluation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


STOCK = 'final_specular_color= lerp(normal_specular_blend_albedo_color, glancing_specular_tint, fresnel_blend);'
H3_ORDER = 'final_specular_color=lerp(lerp(normal_specular_tint,glancing_specular_tint,fresnel_blend),albedo_color,albedo_specular_tint_blend);'


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Expected exactly one source expression/include')
    return source.replace(old, new)


def redirect(data, alias):
    if not re.fullmatch('[a-z0-9_]{6}', alias) or alias == 'shader':
        raise ValueError('Alias must be six ASCII characters and differ from shader')
    old = b'shaders\\shader'
    if data.count(old) != 2:
        raise ValueError('Expected exactly two stock definition/template references')
    return data.replace(old, ('shaders\\'+alias).encode('ascii'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('reach-root', 'dependencies', 'output'):
        parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--shader', action='append', required=True)
    parser.add_argument('--alias', default='h3tint')
    parser.add_argument('--source-directory', default='h3_tint_order')
    args = parser.parse_args()
    redirect(b'shaders\\shader shaders\\shader', args.alias)
    if not re.fullmatch('[a-z0-9_]+', args.source_directory):
        raise ValueError('Source directory must be one lowercase tag component')
    kit = args.reach_root.resolve(strict=True)
    tags = kit/'tags'
    out = args.output.resolve()
    if out.is_relative_to(kit):
        raise ValueError('Backups must be outside the editing kit')
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.dependencies.resolve(strict=True)))
    import clr
    clr.AddReference(str(kit/'bin/ManagedBlam.dll'))
    import Bungie as H
    os.chdir(out)
    startup = H.ManagedBlamStartupParameters()
    startup.InitializationLevel = H.InitializationType.TagsOnly
    system = H.ManagedBlamSystem()
    callback = H.ManagedBlamCrashCallback(lambda info: None)
    system.Start(str(kit), callback, startup)
    report = dict(status='PREFLIGHT', files=[], shaders=[], commands=[])

    def flush():
        (out/'result.json').write_text(json.dumps(report, indent=2))

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def path(rel):
        p = (tags/rel.replace('\\', '/')).resolve()
        if not p.is_relative_to(tags):
            raise ValueError('Tag path escapes kit')
        return p

    def load(rel):
        tag = H.Tags.TagFile()
        name, ext = rel.replace('/', '\\').rsplit('.', 1)
        try:
            tag.Load(H.Tags.TagPath.FromPathAndExtension(name, ext))
        except BaseException:
            tag.Dispose()
            raise
        return tag

    def preserve(rel):
        p = path(rel)
        row = dict(path=str(p), before_sha256=None)
        if p.exists():
            backup = out/'backups'/p.relative_to(tags)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, backup)
            row.update(before_sha256=digest(p), mtime_ns=p.stat().st_mtime_ns,
                       backup=str(backup), size=p.stat().st_size)
            if digest(backup) != row['before_sha256']:
                raise ValueError('Backup hash mismatch')
        report['files'].append(row)
        flush()
        return row

    prefix = 'shaders/'+args.source_directory
    selected = []
    for rel in dict.fromkeys(args.shader):
        if path(rel).suffix != '.shader':
            raise ValueError('Only ordinary shader tags are supported')
        data = path(rel).read_bytes()
        candidate = redirect(data, args.alias)
        tag = load(rel)
        try:
            template = str(tag.SelectField('render_method[0]/postprocess[0]/shader template').Path.RelativePathWithExtension).replace('\\', '/')
        finally:
            tag.Dispose()
        options = Path(template).stem
        if not re.fullmatch(r'(?:_\d+){12}', options) or options.split('_')[5] != '2':
            raise ValueError('Only a twelve-option two-lobe template is supported')
        if template != 'shaders/shader_templates/'+options+'.render_method_template':
            raise ValueError('Expected a stock shader template')
        selected.append((rel, data, candidate, options))

    # Copy only the include chain needed to replace the final Fresnel tint.
    for name in ('shader', 'material_models', 'two_lobe_phong', 'shared_specular'):
        src = 'shaders/templated/'+('' if name == 'shader' else 'materials/')+name+'.hlsl_include'
        dst = prefix+'/'+name+'.hlsl_include'
        tag = load(src)
        try:
            source = str(tag.SelectField('include file').DataAsText).rstrip('\0')
        finally:
            tag.Dispose()
        if name == 'shared_specular':
            expected = replace_once(source, STOCK, H3_ORDER)
        else:
            child = {'shader': 'material_models', 'material_models': 'two_lobe_phong', 'two_lobe_phong': 'shared_specular'}[name]
            expected = replace_once(source, 'templated\\materials\\'+child+'.fx', args.source_directory+'\\'+child+'.fx')
        if not path(dst).exists():
            preserve(dst)
            path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path(src), path(dst))
            tag = load(dst)
            try:
                tag.SelectField('include file').DataAsText = expected
                tag.Save()
            finally:
                tag.Dispose()
        tag = load(dst)
        try:
            if str(tag.SelectField('include file').DataAsText).rstrip('\0') != expected:
                raise ValueError('Existing compatibility include differs: '+dst)
        finally:
            tag.Dispose()

    definition = prefix+'/shader.render_method_definition'
    if not path(definition).exists():
        preserve(definition)
        shutil.copy2(path('shaders/shader.render_method_definition'), path(definition))
        tag = load(definition)
        try:
            tag.SelectField('location').SetStringData(args.source_directory+'\\shader')
            tag.Save()
        finally:
            tag.Dispose()
    alias_definition = 'shaders/'+args.alias+'.render_method_definition'
    if not path(alias_definition).exists():
        preserve(alias_definition)
        shutil.copy2(path(definition), path(alias_definition))
    if path(alias_definition).read_bytes() != path(definition).read_bytes():
        raise ValueError('Alias definition differs')
    for options in sorted({x[3] for x in selected}):
        compiled = prefix+'/shader_templates/'+options
        if not path(compiled+'.render_method_template').exists():
            for ext in ('.render_method_template', '.pixel_shader', '.vertex_shader'):
                preserve(compiled+ext)
            cmd = [str(kit/'tool.exe'), 'generate-specified-template', 'win', prefix.replace('/', '\\')+'\\shader', options]
            with (out/(options+'.compile.log')).open('wb') as log:
                result = subprocess.run(cmd, cwd=kit, stdout=log, stderr=subprocess.STDOUT)
            report['commands'].append(dict(command=cmd, exit_code=result.returncode))
            flush()
            if result.returncode:
                raise RuntimeError('Template compilation failed')
        for ext in ('.render_method_template', '.pixel_shader', '.vertex_shader'):
            tag = load(compiled+ext)
            tag.Dispose()
        alias_template = 'shaders/'+args.alias+'_templates/'+options+'.render_method_template'
        if not path(alias_template).exists():
            preserve(alias_template)
            path(alias_template).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path(compiled+'.render_method_template'), path(alias_template))
        if path(alias_template).read_bytes() != path(compiled+'.render_method_template').read_bytes():
            raise ValueError('Alias template differs')
    # Back up the whole explicit selection before replacing any shader.
    for rel, data, candidate, options in selected:
        preserve(rel)
        if path(rel).read_bytes() != data:
            raise ValueError('Shader changed during preflight')
    for rel, data, candidate, options in selected:
        path(rel).write_bytes(candidate)
        tag = load(rel)
        try:
            actual = str(tag.SelectField('render_method[0]/postprocess[0]/shader template').Path.RelativePathWithExtension).replace('\\', '/')
            if actual != 'shaders/'+args.alias+'_templates/'+options+'.render_method_template':
                raise ValueError('Native template selection differs')
        finally:
            tag.Dispose()
        if path(rel).read_bytes() != candidate:
            raise ValueError('Unexpected tag mutation during readback')
        report['shaders'].append(dict(path=str(path(rel)), sha256=digest(path(rel)), template=actual,
                                      status='NATIVE_READBACK_VERIFIED'))
        flush()
    for row in report['files']:
        p = Path(row['path'])
        row['after_sha256'] = digest(p) if p.exists() else None
    report.update(status='NATIVE_READBACK_VERIFIED', runtime_status='RUNTIME_TEST_PENDING')
    flush()


if __name__ == '__main__':
    main()
