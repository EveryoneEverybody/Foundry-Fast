"""Read native world relationships after ordinary Reach compilation; never edit tags."""
import math
from .native_validation import close


def match_triangles(expected,actual,tolerance=1e-4):
    """One-to-one geometry match, invariant to order and cyclic start, never winding."""
    if len(expected)!=len(actual):raise ValueError('Boundary triangle count differs')
    if any(len(t)!=3 or any(len(p)!=3 or not all(math.isfinite(float(v)) for v in p) for p in t) for t in [*expected,*actual]):
        raise ValueError('Invalid/nonfinite boundary triangle geometry')
    remaining=dict(enumerate(actual));maximum=0.0
    for triangle in expected:
        candidates=[]
        for index,native in remaining.items():
            error=min(max(abs(float(triangle[i][j])-float(native[(i+rotation)%3][j]))
                for i in range(3) for j in range(3)) for rotation in range(3))
            if math.isfinite(error) and error<=tolerance:candidates.append((error,index))
        if not candidates:raise ValueError('Boundary triangle geometry/winding differs: '+str(triangle))
        error,index=min(candidates);remaining.pop(index);maximum=max(maximum,error)
    return maximum


def polygon_area_vector(points):
    origin=points[0];result=[0.0]*3
    for i in range(1,len(points)-1):
        a=[points[i][j]-origin[j] for j in range(3)]
        b=[points[i+1][j]-origin[j] for j in range(3)]
        cross=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
        result=[x+y/2 for x,y in zip(result,cross)]
    return result


def retained_boundary(tag, raw, bsp, seam):
    """Verify the existing inactive seam surface, not a newly invented closure."""
    triangles=[];source_surfaces=set()
    for mesh in bsp['meshes']:
        if mesh['role']!='collision':continue
        for t in mesh['triangles']:
            if bsp['materials'][t['material']].get('source_seam_mapping')==seam['source_index']:
                triangles.append([[v/100 for v in mesh['vertices'][i]['position']] for i in t['vertices']])
                source_surfaces.add(t['source_surface'])
    if not triangles:raise ValueError('Inactive seam has no extant source collision')
    source_points=[v for t in triangles for v in t]
    expected=[sum(v[i] for v in map(polygon_area_vector,triangles)) for i in range(3)]
    actual=[0.0]*3;matches=[]
    materials=tag.SelectField('Block:collision materials').Elements
    for block in ('collision bsp','large collision bsp'):
        for collision in raw.SelectField('Block:'+block).Elements:
            vertices=collision.SelectField('Block:vertices').Elements
            allowed={v.ElementIndex for v in vertices if any(max(abs(a-b) for a,b in zip(v.Fields[0].Data,p))<=1e-4 for p in source_points)}
            if len(allowed)<3:continue
            edges=collision.SelectField('Block:edges').Elements
            for s in collision.SelectField('Block:surfaces').Elements:
                first=int(s.SelectField('first edge').Data);index=first;ring=[];visited=set()
                while index not in visited:
                    if not 0<=index<edges.Count:raise ValueError('Invalid native boundary edge')
                    visited.add(index);edge=edges[index]
                    left=int(edge.SelectField('left surface').Data)==s.ElementIndex
                    vertex=int(edge.SelectField('start vertex' if left else 'end vertex').Data)
                    if vertex not in allowed:break
                    ring.append(list(vertices[vertex].Fields[0].Data))
                    index=int(edge.SelectField('forward edge' if left else 'reverse edge').Data)
                    if index==first:
                        if len(ring)<3:raise ValueError('Invalid native boundary ring')
                        material=materials[int(s.SelectField('material').Data)]
                        if material.SelectField('flags').TestBit('is seam'):
                            raise ValueError('Inactive boundary incorrectly depends on an unbuilt seam')
                        flags=s.SelectField('flags')
                        if flags.TestBit('invisible') or flags.TestBit('invalid'):
                            raise ValueError('Inactive boundary lost ordinary collision')
                        area=polygon_area_vector(ring);actual=[x+y for x,y in zip(actual,area)]
                        matches.append(dict(block=block,surface=s.ElementIndex,vertices=ring))
                        break
    if not matches:raise ValueError('Extant inactive seam collision absent from native BSP')
    close(actual,expected,'inactive seam collision area and winding')
    return dict(source_seam=seam['source_index'],source_surfaces=sorted(source_surfaces),native_surfaces=matches,
        area_vector=actual,status='VERIFIED_EXTANT_COLLISION',active_connection=False,added_geometry=False)


def validate(plan, report, *, collect_transform_errors=False):
    from io_scene_foundry.managed_blam import Tag
    from io_scene_foundry.managed_blam.scenario import ScenarioTag
    world=dict(bsps=[],designs=[],skies=[],seams=[],transform_errors=[])
    report['native_world_readback']=world
    def transform(actual,expected,label):
        try:close(actual,expected,label)
        except ValueError as exc:
            if not collect_transform_errors:raise
            world['transform_errors'].append(dict(label=label,actual=list(actual),expected=list(expected),failure=str(exc)))
    with ScenarioTag(path=plan['target']['scenario'],tag_must_exist=True) as tag:
        full = plan.get('selection', {}).get('scope') == 'FULL_SCENARIO'
        if full:
            from .native_zones import readback
            world['zone_sets'] = readback(tag, plan)
        elif tag.block_zone_sets.Elements.Count!=1:
            raise ValueError('Unexpected generated zone-set count')
        zone=tag.block_zone_sets.Elements[plan['selection']['source_zone_index'] if full else 0]
        if zone.SelectField('name').GetStringData()!=plan['scenario']['zone_set']:
            raise ValueError('Native zone-set identity differs')
        design_mask=sum(1<<i for i,v in enumerate(zone.SelectField('structure design zone flags').Items) if v.IsSet)
        expected_design = (plan['selection']['zone_sets'][plan['selection']['source_zone_index']]['target_design_mask']
                           if full else (1<<len(plan['structure_designs']))-1)
        if design_mask!=expected_design:
            raise ValueError('Native zone-set design membership differs')
        for e,b in zip(tag.block_bsps.Elements,plan['bsps']):
            close(e.SelectField('default sky').Value,b['default_sky'],'BSP default sky')
        for e,s in zip(tag.block_skies.Elements,plan['skies']):
            mask=sum(1<<i for i,v in enumerate(e.SelectField('active on bsps').Items) if v.IsSet)
            close(mask,s['active_bsp_mask'],'sky BSP membership')
        starts=tag.tag.SelectField('Block:player starting locations').Elements
        if starts.Count!=1:raise ValueError('Expected one source-authored player start')
        close(starts[0].SelectField('facing').Data,plan['scenario']['spawn']['facing_degrees'],'source-authored spawn facing')
        world['spawn_facing_degrees']=float(starts[0].SelectField('facing').Data)
        world['structure_design_mask']=design_mask
    for bsp in plan['bsps']:
        with Tag(path=bsp['destination'],tag_must_exist=True) as tag:
            raw=tag.tag.SelectField('Struct:resource interface[0]/Block:raw_resources[0]/Struct:raw_items').Elements[0]
            definitions=raw.SelectField('Block:instanced geometries definitions').Elements
            instances=tag.tag.SelectField('Block:instanced geometry instances').Elements
            by_name={e.SelectField('name').GetStringData():e for e in instances}
            proofs={u['source_definition']:u for u in bsp['instance_plan'].get('unified_breakable_definitions',[])}
            split_count=sum(bool(proofs.get(p['source_definition'],{}).get('partition')) for p in bsp['instance_plan']['placements'])
            if len(by_name)!=len(bsp['instance_plan']['placements'])+split_count:
                raise ValueError('Native placement names/counts differ')
            proofs={u['source_definition']:u for u in bsp['instance_plan'].get('unified_breakable_definitions',[])}
            placements=[]
            for p in bsp['instance_plan']['placements']:
                name=bsp['region']+'_'+str(p['source_index'])+'_'+p['name'].lstrip('!?@')
                if name not in by_name:raise ValueError('Native source instance absent: '+name)
                e=by_name[name];scale=float(e.SelectField('scale').Data)
                errors_before=len(world['transform_errors'])
                transform(e.SelectField('position').Data,[p['matrix'][i][3]/100 for i in range(3)],name+' origin')
                for column,axis in enumerate(('forward','left','up')):
                    transform([v*scale for v in e.SelectField(axis).Data],[p['matrix'][i][column] for i in range(3)],name+' '+axis)
                policy=e.SelectField('imposter policy')
                if str(policy.Items[policy.Value].EnumName)!='never':
                    raise ValueError('Native instance requires an ungenerated imposter: '+name)
                index=e.SelectField('instance definition').Value
                if not 0<=index<definitions.Count:raise ValueError('Invalid native instance definition: '+name)
                d=definitions[index];surfaces=d.SelectField('Struct:collision info[0]/Block:surfaces').Elements
                expected_collision=p['collision_definition'] is not None
                if bool(surfaces.Count)!=expected_collision:
                    raise ValueError('Native instance collision presence differs from source: '+name)
                item=dict(source_placement=p['source_index'],source_definition=p['source_definition'],name=name,
                    native_placement=e.ElementIndex,native_definition=index,collision_surfaces=surfaces.Count,
                    imposter_policy='never',transform='VERIFIED' if len(world['transform_errors'])==errors_before else 'UNRESOLVED_NATIVE_DIFFERENCE')
                proof=proofs.get(p['source_definition'],{})
                if proof and not proof.get('partition'):
                    if not surfaces.Count or any(not s.SelectField('flags').TestBit('breakable') for s in surfaces):
                        raise ValueError('Unified glass lost native breakable collision: '+name)
                    sets=d.SelectField('Block:breakable surface sets').Elements.Count
                    mappings=d.SelectField('Block:surface to triangle mapping').Elements.Count
                    if not sets or not mappings:raise ValueError('Native breakable render/collision relationship missing: '+name)
                    item['breakable']=dict(subsystem='BSP_BREAKABLE_SURFACES',surface_sets=sets,render_mappings=mappings)
                placements.append(item)
                if proof.get('partition'):
                    split_name=name+proof['partition']['generated_instance_suffix']
                    if split_name not in by_name:raise ValueError('Native split glass instance absent: '+split_name)
                    split=by_name[split_name];split_scale=float(split.SelectField('scale').Data)
                    close(split.SelectField('position').Data,[p['matrix'][i][3]/100 for i in range(3)],split_name+' origin')
                    for column,axis in enumerate(('forward','left','up')):
                        close([v*split_scale for v in split.SelectField(axis).Data],[p['matrix'][i][column] for i in range(3)],split_name+' '+axis)
                    split_index=split.SelectField('instance definition').Value
                    if not 0<=split_index<definitions.Count:raise ValueError('Invalid native split glass definition')
                    sd=definitions[split_index];ss=sd.SelectField('Struct:collision info[0]/Block:surfaces').Elements
                    sets=sd.SelectField('Block:breakable surface sets').Elements.Count
                    mappings=sd.SelectField('Block:surface to triangle mapping').Elements.Count
                    if not ss.Count or any(not s.SelectField('flags').TestBit('breakable') for s in ss) or not sets or not mappings:
                        raise ValueError('Native split glass lost breakable geometry/linkage: '+split_name)
                    if any(s.SelectField('flags').TestBit('breakable') for s in surfaces):
                        raise ValueError('Native solid frame incorrectly became breakable: '+name)
                    item['partition']=dict(name=split_name,native_placement=split.ElementIndex,native_definition=split_index,
                        transform='VERIFIED',breakable_surfaces=ss.Count,surface_sets=sets,render_mappings=mappings,
                        source_partition=proof['partition'])
            collision=raw.SelectField('Block:collision bsp').Elements
            large=raw.SelectField('Block:large collision bsp').Elements
            surface_count=sum(b.SelectField('Block:surfaces').Elements.Count for b in [*collision,*large])
            if not surface_count:raise ValueError('Native BSP has no collision surfaces')
            skies=[e.SelectField('scenario sky index').Data for e in tag.tag.SelectField('Block:clusters').Elements]
            sky_map={s['source_index']:s['target_index'] for s in plan['selection']['skies']}
            source_skies={int(c['scenario sky index']) for c in bsp['authoring']['clusters']}
            allowed_skies={-1,bsp['default_sky']}|{sky_map[i] for i in source_skies if i>=0}
            if any(i not in allowed_skies for i in skies):raise ValueError('Unexpected native cluster sky identity')
            bounds=[list(tag.tag.SelectField('world bounds '+axis).Data) for axis in 'xyz']
            if any(len(v)!=2 or not all(math.isfinite(x) for x in v) or v[0]>=v[1] for v in bounds):
                raise ValueError('Invalid native world bounds')
            seams=[]
            for e in tag.tag.SelectField('Block:seam identifiers').Elements:
                clusters=e.SelectField('Block:cluster mapping').Elements
                seams.append(dict(index=e.ElementIndex,clusters=[c.Fields[0].Data for c in clusters if c.Fields[0].Data>=0]))
            inactive=[retained_boundary(tag.tag,raw,bsp,s) for s in plan['seams'] if s.get('selected_state') and
                any(o['source_bsp_index']==bsp['source_index'] for o in s['owners'])]
            world['bsps'].append(dict(source=bsp['source_tag'],path=bsp['destination'],placements=placements,
                collision_surfaces=surface_count,cluster_skies=skies,source_cluster_skies=sorted(source_skies),seam_ownership=seams,
                inactive_seam_collision=inactive,
                world_bounds=bounds,source_world_bounds=[b['values'] for b in bsp['authoring']['world_bounds']],
                bounds_strategy='Reach Tool rebuilds structure bounds; instance bounds and transforms remain separate',
                source_authored_portals=len(bsp['portals']),native_portals=tag.tag.SelectField('Block:cluster portals').Elements.Count,
                portal_strategy='All source portal polygons authored in GR2; Tool regenerates and may merge portal/cluster topology'))
        design=bsp['structure_design']
        if design is None:
            continue
        with Tag(path=design['destination'],tag_must_exist=True) as tag:
            native=tag.tag.SelectField('Struct:physics[0]/Block:soft ceilings block').Elements
            by_name={e.SelectField('name').GetStringData():e for e in native}
            if set(by_name)!={d['name'] for d in design['meshes']}:raise ValueError('Native design boundaries differ')
            rows=[]
            for d in design['meshes']:
                e=by_name[d['name']]
                close(e.SelectField('type').Value,{'SOFT_CEILING':0,'SOFT_KILL':1,'SLIP_SURFACE':2}[d['boundary_surface_type']],d['name']+' boundary type')
                actual=[[list(t.SelectField('vertex'+str(i)).Data) for i in range(3)]
                    for t in e.SelectField('Block:soft ceiling triangles').Elements]
                error=match_triangles(d['triangles_world'],actual)
                rows.append(dict(name=d['name'],triangles=len(actual),type=d['boundary_surface_type'],geometry='VERIFIED',maximum_coordinate_error_world=error))
            world['designs'].append(dict(path=design['destination'],boundaries=rows))
    active=[s for s in plan['seams'] if not s.get('selected_state')]
    with Tag(path=plan['target']['scenario'].rsplit('.',1)[0]+'.structure_seams',tag_must_exist=True) as tag:
        native=tag.tag.SelectField('Block:seams').Elements
        if native.Count!=len(active):raise ValueError('Native active seam count differs')
        for source in active:
            matches=[]
            for e in native:
                points=[list(v.Fields[0].Data) for v in e.SelectField('Struct:original[0]/Block:original vertices').Elements]
                if (len(points)==len(source['vertices_world']) and all(any(
                    max(abs(a-b) for a,b in zip(v,p))<=1e-4 for p in points) for v in source['vertices_world'])):
                    matches.append(e.ElementIndex)
            if len(matches)!=1:raise ValueError('Native seam source geometry match is missing or ambiguous')
            index=matches[0]
            owners=[i for i,b in enumerate(world['bsps']) if any(s['index']==index and s['clusters'] for s in b['seam_ownership'])]
            expected_owners=sorted(next(i for i,b in enumerate(plan['bsps']) if b['source_index']==o['source_bsp_index']) for o in source['owners'])
            if owners!=expected_owners:raise ValueError('Native seam owner linkage differs')
            world['seams'].append(dict(source_seam=source['source_index'],native_seam=index,owners=owners,geometry='VERIFIED'))
    for sky in plan['skies']:
        spec=sky['lighting'];path=sky['destination'].rsplit('.',1)[0]
        with Tag(path=path+'.render_model',tag_must_exist=True) as tag:
            samples=tag.tag.SelectField('Block:sky lights').Elements
            close(samples.Count,len(spec['source_samples']),'native sky sample count')
            for e,s in zip(list(samples)[:-1],spec['source_samples'][:-1]):
                for field,key in [('direction','direction'),('intensity','intensity'),('solid angle','solid_angle')]:
                    close(e.SelectField(field).Data,s[key],'sky sample '+str(e.ElementIndex)+' '+field)
            sun=[e.Fields[0].Data for e in tag.tag.SelectField('Array:sun').Elements]
            close(sun[:3],spec['source_samples'][-1]['direction'],'source sun direction')
            close(sun[3:],spec['sun_irradiance'],'source sun irradiance')
            world['skies'].append(dict(path=path+'.render_model',samples=samples.Count,sun=sun,source_samples='VERIFIED'))
        with Tag(path=path+'.model',tag_must_exist=True) as tag:
            p=tag.tag.SelectField('ShortEnum:imposter policy')
            if str(p.Items[p.Value].EnumName)!='never':raise ValueError('Native sky requires an ungenerated imposter')
    world['status']='FAILED_TRANSFORM_READBACK' if world['transform_errors'] else 'VERIFIED_NATIVE_AUTHORING'
    if world['transform_errors']:raise ValueError(str(len(world['transform_errors']))+' native instance transform components differ; all differences retained')
