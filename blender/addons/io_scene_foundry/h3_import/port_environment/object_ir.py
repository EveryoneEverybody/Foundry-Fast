"""Shared source object dependencies; no unit-specific or runtime-resource code."""
from collections import Counter
from .paths import relative


def field(rows, name):
    matches = [r for r in rows if r['name'] == name]
    if len(matches) > 1:
        raise ValueError('Ambiguous source authoring field: '+name)
    return matches[0] if matches else None


def scalar(row, default=None):
    if row is None:
        return default
    value = row.get('value')
    if isinstance(value, dict):
        if 'values' in value:
            return value['values'][0] if len(value['values'])==1 else value['values']
        if 'value' in value:
            return value['value']
    return value


def walk(rows, prefix=''):
    for row in rows:
        path = prefix+'/'+row['name']
        yield path, row
        if 'fields' in row:
            yield from walk(row['fields'],path)
        for element in row.get('elements',[]):
            yield from walk(element['fields'],path+'['+str(element['source_index'])+']')


def references(metadata):
    out=[]
    for path,row in walk(metadata['fields']):
        value=row.get('value')
        if isinstance(value,dict) and value.get('path') and value.get('extension'):
            out.append(dict(source_field=path,source_tag=relative(value['path']).as_posix()+'.'+value['extension'],
                            source_group=value['extension']))
    return out


def dependency(metadata, name):
    candidates=[r for r in references(metadata) if r['source_field'].rsplit('/',1)[-1]==name]
    if len(candidates)>1:
        raise ValueError('Ambiguous shared object dependency: '+name)
    return candidates[0]['source_tag'] if candidates else None


def describe(identity, metadata, model=None, geometry=None, physics=None):
    result=dict(identity, source_sha256=metadata['source_sha256'],source_authoring=metadata['fields'],
                dependency_provenance=references(metadata),status='SOURCE_DECODED',native_status='NOT_GENERATED')
    result['model']=dependency(metadata,'model')
    if model:
        for name,key in [('render model','render_model'),('collision model','collision_model'),
                         ('physics model','physics_model'),('animation','animation_graph'),('animation graph','animation_graph')]:
            value=dependency(model,name)
            if value:result[key]=value
        result['model_authoring']=model['fields']
        result['dependency_provenance']+=references(model)
    result['functions']=[dict(source_field=p,record=r) for p,r in walk(metadata['fields']) if r['name']=='functions']
    result['bounds']={p:scalar(r) for p,r in walk(metadata['fields']) if r['name'] in
                      {'bounding radius','bounding offset','dynamic light sphere radius','acceleration scale'}}
    if geometry:
        result['variants']=geometry.get('variants',[])
        result['default_variant']=geometry.get('default_variant','')
        result['materials']=geometry.get('shader_paths',[])
        result['geometry_summary']={role:dict(vertices=len(geometry[role].get('vertices',[])),
            triangles=len(geometry[role].get('triangles',[])),nodes=len(geometry[role].get('nodes',[])))
            for role in ('render','collision') if geometry.get(role)}
        if geometry.get('physics'):
            p=geometry['physics'];result['physics_summary']=dict(shapes=dict(Counter(s['kind'] for s in p['shapes'])),
                capsules=p.get('capsules_in_source',0),ragdolls=p.get('ragdolls_in_source',0),hinges=p.get('hinges_in_source',0))
    if physics:
        result['physics_authoring']=physics['fields']
    return result
