"""Build normal Foundry scenario authoring from the accepted multi-BSP IR."""
from copy import deepcopy
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace
from . import authoring, native_contracts, native_topology
from .model import stable_hash
from .light_units import reach_attenuation_units


def face_property(mesh, kind, values, indices=None):
    import bpy
    selected = set(range(len(mesh.polygons))) if indices is None else set(indices)
    if not selected:
        return
    prop = mesh.nwo.face_props.add()
    prop.type = kind
    for key,value in values.items():
        setattr(prop, key, value)
    attr = mesh.attributes.new(name='h3_'+kind+'_'+str(len(mesh.nwo.face_props)), type='BOOLEAN', domain='FACE')
    attr.data.foreach_set('value', [i in selected for i in range(len(mesh.polygons))])
    prop.attribute_name, prop.face_count = attr.name, len(selected)
    return prop


def polygon_record(points, triangles, mesh_type):
    return dict(vertices=[dict(position=[v*100 for v in p],normal=[0,0,1],uvs=[],weights=[]) for p in points],
        triangles=[dict(vertices=t,material=0) for t in triangles],mesh_type=mesh_type)


def repair_seam_ownership(scene, plan, report):
    """Repair only metadata on a hash-verified saved source scene."""
    import bpy
    provenance=bpy.data.texts.get('H3 accepted environment provenance')
    if not provenance or json.loads(provenance.as_string())['plan_sha256']!=plan['plan_sha256']:
        raise ValueError('Saved scene does not carry the accepted source plan')
    rows=[]
    for seam in plan['seams']:
        if seam.get('selected_state'):continue
        ob=scene.objects.get('h3_seam_'+str(seam['source_index']))
        if ob is None or ob.get('h3_port_role')!='seam':raise ValueError('Saved source seam is absent')
        expected=polygon_record(seam['vertices_world'],seam['triangles'],'_connected_geometry_mesh_type_seam')
        if (ob.data.nwo.mesh_type!=expected['mesh_type'] or len(ob.data.vertices)!=len(expected['vertices']) or
                [list(p.vertices) for p in ob.data.polygons]!=seam['triangles'] or
                any(abs(ob.matrix_world[r][c]-(r==c))>1e-7 for r in range(4) for c in range(4))):
            raise ValueError('Saved seam geometry/type/transform differs from source')
        error=max(abs(v.co[i]-e['position'][i]) for v,e in zip(ob.data.vertices,expected['vertices']) for i in range(3))
        if error>.01:raise ValueError('Saved seam coordinates differ beyond float32 rounding')
        owners=native_contracts.seam_owner_order(seam,plan['bsps'])
        regions=[next(b['region'] for b in plan['bsps'] if b['source_index']==o['source_bsp_index']) for o in owners]
        rows.append(dict(source_seam=seam['source_index'],owners=owners,maximum_rounding_ass=error,
            previous_front=ob.nwo.region_name,previous_back=ob.nwo.seam_back,front=regions[0],back=regions[1]))
        ob.nwo.region_name=regions[0];ob.nwo.seam_back=regions[1];ob.nwo.seam_back_manual=False
    report['seam_orientation']=rows
    report['scene_resume_changes']='Seam front/back BSP metadata only; source vertices, triangles and winding retained'


def render_properties(ob, record, parts, material_rows, source_materials):
    # A part owns a shader slot. The decoder preserves this assignment even
    # when degenerate indices were removed during triangle reconstruction.
    by_slot = {}
    faces_by_slot = {}
    for i,triangle in enumerate(record['triangles']):
        faces_by_slot.setdefault(triangle['material'], []).append(i)
    for part in parts:
        profile = (part['part type'], authoring.number(part['part flags']))
        by_slot.setdefault(part['render method index'], set()).add(profile)
    for slot, profiles in by_slot.items():
        selected = faces_by_slot.get(slot, [])
        if not selected:
            continue
        if len(profiles) != 1:
            raise ValueError(f'Ambiguous per-part face semantics on {ob.name}, material {slot}')
        kind,flags = next(iter(profiles))
        if kind not in {2,3,4,5} or flags & ~2:
            raise ValueError('Unmapped native render part')
        if kind == 3:
            face_property(ob.data,'no_shadow',dict(no_shadow=True),selected)
        if kind == 4:
            face_property(ob.data,'transparent',dict(transparent=True),selected)
        if kind == 5:
            face_property(ob.data,'face_mode',dict(face_mode='lightmap_only'),selected)
        if flags & 2:
            face_property(ob.data,'no_lightmap',dict(no_lightmap=True),selected)
    from io_scene_foundry import utils
    from io_scene_foundry.constants import WU_SCALAR
    for slot,selected in faces_by_slot.items():
        row = material_rows[slot]
        if slot < len(source_materials):
            for prop in source_materials[slot]['properties']:
                name=prop['type']['name']
                if name=='lightmap resolution':
                    source_value=authoring.number(prop['real-value'])
                    # Reach's normal importer clamps this authoring scale to
                    # its seven supported density levels. Keep fractional H3
                    # requests in provenance; this changes bake density only.
                    value=str(max(1,min(7,round(source_value))))
                    face_property(ob.data,'lightmap_resolution_scale',dict(lightmap_resolution_scale=value),selected)
                elif name=='lightmap transparency override':
                    face_property(ob.data,'lightmap_transparency_override',
                        dict(lightmap_transparency_override=bool(prop['int-value'])),selected)
                elif name=='lightmap additive transparency':
                    packed=prop['long-value']
                    face_property(ob.data,'lightmap_additive_transparency',
                        dict(lightmap_additive_transparency=[(packed>>s & 255)/255 for s in (16,8,0)]),selected)
                else:
                    raise ValueError('Unmapped embedded lighting property: '+name)
        light = row.get('lighting', {})
        if not selected or float(light.get('emissive power',0)) <= 0:
            continue
        source_focus = float(light['emissive focus'])
        focus = math.pi*(1-source_focus)
        if row.get('emissive_authoring'):
            focus = row['emissive_authoring']['target']['foundry_emissive_spread_radians']
        color = authoring.vector(light['emissive color'])
        face_property(ob.data,'emissive',dict(
            material_lighting_emissive_power=float(light['emissive power']),
            material_lighting_emissive_color=[utils.srgb_to_linear(v) for v in color],
            material_lighting_emissive_per_unit=bool(int(light['flags']) & 2),
            material_lighting_emissive_quality=float(light['emissive quality']),
            material_lighting_emissive_focus=focus,
            material_lighting_attenuation_cutoff=float(light['attenuation cutoff'])/(100*WU_SCALAR),
            material_lighting_attenuation_falloff=float(light['attenuation falloff'])/(100*WU_SCALAR)),selected)


def collision_record(definition, bsp, material_rows):
    source=definition['collision_mesh']
    record = native_topology.collision_polygons(source,source['source_surfaces'],bsp['source_tag']+' embedded collision')
    source_mats = bsp['authoring']['collision_materials']
    slots = {m.get('source_shader'):i for i,m in enumerate(material_rows) if m.get('source_shader')}
    default_slot = len(material_rows)-1
    for triangle in record['triangles']:
        index = triangle['material']
        shader = None
        if index >= 0:
            ref = source_mats[index]['render method']
            if ref:
                shader = (ref['path']+'.'+ref['extension']).replace('\\','/')
        if shader and shader not in slots:
            raise ValueError('Collision shader missing from native material plan: '+shader)
        triangle['material'] = slots[shader] if shader else default_slot
    record.update(mesh_type='_connected_geometry_mesh_type_default')
    return record


def collision_properties(ob, record):
    grouped = {}
    for surface in record['source_surfaces']:
        flags = authoring.number(surface['flags'])
        grouped.setdefault(flags, []).extend(range(surface['triangle_start'],surface['triangle_start']+surface['triangle_count']))
    for flags,indices in grouped.items():
        props = native_contracts.collision_face(flags)
        face_property(ob.data,'face_mode',dict(face_mode=props['face_mode']),indices)
        if props['two_sided']:
            face_property(ob.data,'face_sides',dict(two_sided=True),indices)
        if props['ladder']:
            face_property(ob.data,'ladder',dict(ladder=True),indices)


def construct(scene, plan, config, mats, report, mesh_object):
    import bpy
    from mathutils import Matrix
    from io_scene_foundry import utils
    nwo = utils.get_scene_props()
    nwo.regions_table.clear()
    for bsp in plan['bsps']:
        print('Constructing source BSP '+str(bsp['source_index'])+': '+bsp['source_tag'],flush=True)
        nwo.regions_table.add().name=bsp['region']
    report['native_construction'] = []
    timings=report.setdefault('native_stage_seconds',{})
    def elapsed(name,start):
        timings[name]=timings.get(name,0)+time.perf_counter()-start
    source_run = Path(config['snapshot_input']['source_run']) if config.get('snapshot_input') else Path(config['run_directory'])
    for bsp in plan['bsps']:
        began=time.perf_counter()
        region = bsp['region']
        decoded = json.loads((source_run/'source'/bsp['geometry_source']['file']).read_text())
        if stable_hash(decoded) != bsp['geometry_source']['canonical_sha256']:
            raise ValueError('Decoded BSP changed before native construction')
        elapsed('accepted geometry JSON verification',began)
        began=time.perf_counter()
        material_rows = deepcopy(bsp['materials'])
        # Embedded instance collision can reference a shader that has no root
        # BSP surfaces. Keep the original render slots, then append that exact
        # source identity from the already validated shared material plan.
        known = {m.get('source_shader') for m in material_rows}
        for source in bsp['authoring']['collision_materials']:
            ref = source.get('render method')
            if not ref:
                continue
            identity = (ref['path']+'.'+ref['extension']).replace('\\','/')
            if identity not in known and identity in mats:
                material_rows.append(dict(source_shader=identity, source_collision_material=source['source_index']))
                known.add(identity)
        material_rows.append(dict(name='collision_default',source_shader=None))
        # An untextured collision shell has no source shader. This is a special
        # collision material definition, never visible replacement geometry.
        default = bpy.data.materials.new(region+'_collision_default')
        # Tool still requires a valid render-method reference on collision-only
        # source. Reuse an owned H3-derived shader; the explicit collision face
        # mode prevents rendering and the global material remains "default".
        default.nwo.shader_path=next(mats[m['source_shader']].nwo.shader_path
            for m in material_rows if m.get('source_shader') in mats)
        face = default.nwo.material_props.add();face.type='global_material';face.global_material='default'
        bmats = []
        for row in material_rows:
            if row.get('special') == 'sky':
                bmats.append(bpy.data.materials.new(row['name']))
            else:
                bmats.append(mats.get(row.get('source_shader'),default))
        count = dict(region=region,base_meshes=0,placements=0,collision_only_placements=0,unified_breakable_placements=0)
        for index, original in enumerate(bsp['meshes']):
            record = deepcopy(original)
            if record['role']=='render':
                record=native_topology.render_slivers(record,bsp['source_tag']+' '+record['name'])
                report.setdefault('render_slivers',[]).append(record['render_slivers'])
            if record['role'] == 'collision':
                record=native_topology.collision_polygons(record,decoded['environment_semantics']['collision_surfaces'],bsp['source_tag'])
                report.setdefault('collision_topology',[]).append(record['native_topology'])
                # A paired seam is authored once below; its inverted partner is
                # generated by Foundry. The inactive neighbor's extant source
                # faces remain ordinary collision, with exact original winding.
                record['triangles'] = [t for t in record['triangles'] if not (
                    t.get('surface_type') == 'seam' and any(s['source_index']==bsp['materials'][t['material']]['source_seam_mapping']
                        and not s.get('selected_state') for s in plan['seams']))]
            ob,stats = mesh_object(record,bmats,scene,region,region+'_base_'+str(index),record['role'])
            if record['role']=='render':
                ci = int(record['name'].split('_')[-1])
                mesh_index = bsp['authoring']['clusters'][ci]['mesh index']
                render_properties(ob,record,bsp['authoring']['render_meshes'][mesh_index]['parts'],material_rows,bsp['authoring']['materials'])
            else:
                ids=[i for i,t in enumerate(record['triangles']) if t.get('two_sided')]
                face_property(ob.data,'face_sides',dict(two_sided=True),ids)
                ladders=[i for i,t in enumerate(record['triangles']) if t.get('ladder')]
                if ladders:
                    face_property(ob.data,'ladder',dict(ladder=True),ladders)
            report['geometry'].append(stats); count['base_meshes']+=1
        elapsed('BSP construction',began)
        began=time.perf_counter()
        templates={}; split_templates={}
        proofs={u['source_definition']:u for u in bsp['instance_plan'].get('unified_breakable_definitions',[])}
        for placement in bsp['instance_plan']['placements']:
            di=placement['source_definition']
            partition=proofs.get(di,{}).get('partition')
            key=(di,placement['render_object'],placement['collision_definition'] is not None)
            if key not in templates:
                definition=decoded['environment_semantics']['authoring']['definitions'][di]
                source_render=placement['render_object']
                if source_render is None:
                    if placement['collision_definition'] is None:
                        raise ValueError('Empty instance has no authored native representation')
                    record=collision_record(definition,bsp,material_rows)
                else:
                    record=deepcopy(decoded['objects'][source_render])
                    record.update(mesh_type='_connected_geometry_mesh_type_default',face_mode='render_only')
                    if partition:
                        record['triangles']=[record['triangles'][i] for i in partition['solid_render_triangles']]
                    elif di in proofs:
                        record=native_contracts.unified_mesh(record,proofs[di])
                    else:
                        record=native_topology.render_slivers(record,bsp['source_tag']+' definition '+str(di))
                        report.setdefault('render_slivers',[]).append(record['render_slivers'])
                ob,stats=mesh_object(record,bmats,scene,region,f'{region}_def_{di}',record.get('role','instance'))
                if source_render is None:
                    collision_properties(ob,record)
                else:
                    render_properties(ob,record,bsp['authoring']['render_meshes'][definition['mesh index']]['parts'],material_rows,bsp['authoring']['materials'])
                    if di in proofs and not partition:
                        face_property(ob.data,'face_sides',dict(two_sided=True))
                    elif placement['collision_definition'] is not None:
                        solid_definition=definition
                        if partition:
                            mesh=definition['collision_mesh']
                            solid_definition=dict(definition,collision_mesh=dict(mesh,source_surfaces=[s for s in mesh['source_surfaces']
                                if s['source_surface'] in partition['solid_collision_surfaces']]))
                        proxy_record=collision_record(solid_definition,bsp,material_rows)
                        report.setdefault('collision_topology',[]).append(dict(proxy_record['native_topology'],definition=di))
                        proxy,_=mesh_object(proxy_record,bmats,scene,region,f'{region}_collision_{di}','collision_proxy')
                        proxy.nwo.export_this=False
                        collision_properties(proxy,proxy_record)
                        ob.data.nwo.proxy_collision=proxy
                templates[key]=ob
                report['geometry'].append(stats)
                if partition:
                    record=native_contracts.unified_mesh(decoded['objects'][source_render],proofs[di])
                    glass,stats=mesh_object(record,bmats,scene,region,f'{region}_def_{di}_breakable','unified_breakable')
                    render_properties(glass,record,bsp['authoring']['render_meshes'][definition['mesh index']]['parts'],material_rows,bsp['authoring']['materials'])
                    face_property(glass.data,'face_sides',dict(two_sided=True))
                    split_templates[key]=glass
                    report['geometry'].append(stats)
            else:
                ob=templates[key].copy()
                scene.collection.objects.link(ob)
                if partition:
                    glass=split_templates[key].copy()
                    scene.collection.objects.link(glass)
            ob.name=region+'_'+str(placement['source_index'])+'_'+placement['name'].lstrip('!?@')
            ob.matrix_world=Matrix(placement['matrix'])
            source_fields=placement['source_fields']
            ob.nwo.poop_lighting={'per-pixel shared':'per_pixel','per-vertex':'per_vertex',
                'single-probe':'single_probe','per-pixel':'per_pixel'}[source_fields['lightmapping policy']['name']]
            ob.nwo.poop_lightmap_resolution_scale=authoring.number(source_fields['lightmap resolution scale'])
            ob.nwo.poop_pathfinding={'cut-out':'cutout','static':'static','none':'none'}[source_fields['pathfinding policy']['name']]
            ob.nwo.poop_imposter_policy='never'
            ob['h3_source_bsp']=bsp['source_tag'];ob['h3_source_placement']=placement['source_index']
            if partition:
                glass.name=ob.name+partition['generated_instance_suffix']
                glass.matrix_world=ob.matrix_world.copy()
                for name in ('poop_lighting','poop_lightmap_resolution_scale','poop_pathfinding','poop_imposter_policy'):
                    setattr(glass.nwo,name,getattr(ob.nwo,name))
                glass['h3_source_bsp']=bsp['source_tag'];glass['h3_source_placement']=placement['source_index']
                glass['h3_source_partition']='Proven breakable glass partition; solid frame retained in '+ob.name
                count['partitioned_breakable_placements']=count.get('partitioned_breakable_placements',0)+1
            count['placements']+=1
            count['collision_only_placements']+=placement['render_object'] is None
            count['unified_breakable_placements']+=di in proofs
        elapsed('instance construction',began)
        began=time.perf_counter()
        for portal in bsp['portals']:
            points=portal['vertices_world']
            record=polygon_record(points,[list(range(len(points)))],portal['mesh_type'])
            ob,_=mesh_object(record,[default],scene,region,f'{region}_portal_{portal["source_index"]}','portal')
            ob.nwo.portal_type=portal['portal_type'];ob.nwo.portal_is_door=portal['portal_is_door']
        elapsed('BSP construction',began)
        began=time.perf_counter()
        for design in (bsp.get('structure_design') or {}).get('meshes',[]):
            points=[p for tri in design['triangles_world'] for p in tri]
            record=polygon_record(points,[list(range(i,i+3)) for i in range(0,len(points),3)],design['mesh_type'])
            ob,_=mesh_object(record,[default],scene,region,design['name'],'structure_design')
            ob.data.nwo.boundary_surface_type=design['boundary_surface_type']
        elapsed('structure design',began)
        report['native_construction'].append(count)
    began=time.perf_counter()
    for seam in plan['seams']:
        if seam.get('selected_state'):
            continue
        orientation=native_contracts.seam_owner_order(seam,plan['bsps'])
        report.setdefault('seam_orientation',[]).append(dict(source_seam=seam['source_index'],owners=orientation))
        owners=[next(b for b in plan['bsps'] if b['source_index']==o['source_bsp_index']) for o in orientation]
        if len(owners)!=2:
            raise ValueError('Native active seam does not have exactly two selected owners')
        record=polygon_record(seam['vertices_world'],seam['triangles'],'_connected_geometry_mesh_type_seam')
        ob,_=mesh_object(record,[default],scene,owners[0]['region'],'h3_seam_'+str(seam['source_index']),'seam')
        ob.nwo.seam_back=owners[1]['region'];ob.nwo.seam_back_manual=False
    elapsed('BSP construction',began)
    text=bpy.data.texts.new('H3 accepted environment provenance')
    text.write(json.dumps(dict(source=plan['source'],selection=plan['selection'],plan_sha256=plan['plan_sha256'],
        global_seams=plan['seam_source_context'],lighting=plan['lighting_by_bsp']),indent=1))
    bpy.context.view_layer.update()


def write_static_lights(plan, report, *, attenuation_only=False):
    """Use Foundry's native lighting authoring writer, with explicit BSP ownership."""
    from io_scene_foundry.managed_blam.scenario_structure_lighting_info import ScenarioStructureLightingInfoTag
    report['static_light_authoring']=[]
    for bsp,lighting in zip(plan['bsps'],plan['lighting_by_bsp']):
        definitions=[]
        for d in lighting['definitions']:
            definitions.append(SimpleNamespace(**{k:v for k,v in d.items() if k not in {'source_fields','shape'}},
                shape={'rectangle':0,'circle':1}[d['source_fields']['shape']],
                data_name=f'{bsp["region"]}_light_{d["source_index"]}',
                near_attenuation_start=reach_attenuation_units(d['near_attenuation'][0]),near_attenuation_end=reach_attenuation_units(d['near_attenuation'][1]),
                far_attenuation_start=reach_attenuation_units(d['far_attenuation'][0]),far_attenuation_end=reach_attenuation_units(d['far_attenuation'][1]),
                inverse_squared_falloff=False))
        instances=[SimpleNamespace(**i,data_name=definitions[i['definition_index']].data_name,
            game_type=0,screen_space_specular=False,bounce_ratio=1.0,volume_distance=0.0,volume_intensity=0.0,
            fade_out_distance=0.0,fade_start_distance=0.0,light_tag='',shader='',gel='',lens_flare='') for i in lighting['instances']]
        path=bsp['destination'].rsplit('.',1)[0]+'.scenario_structure_lighting_info'
        with ScenarioStructureLightingInfoTag(path=path,tag_must_exist=True) as tag:
            before_materials=tag.tag.SelectField('Block:material info').Elements.Count
            if attenuation_only:
                # Existing accepted tags may contain user-owned controls. The
                # prepare workflow updates only the four converted distances.
                tag.update_reach_attenuation(definitions)
                tag.tag.Save()
                report['static_light_authoring'].append(dict(path=path, definitions=len(definitions),
                    mode='ATTENUATION_ONLY', source_bsp=bsp['source_tag']))
                continue
            tag.build_tag(instances,definitions)
            # Foundry's ordinary writer enables far attenuation by default.
            # Restore the decoded authored flags by name, not numeric analogy.
            for element,d in zip(tag.block_generic_light_definitions.Elements,lighting['definitions']):
                flags=element.SelectField('flags')
                flags.SetBit('use near attenuation',bool(d['flags'] & 1))
                flags.SetBit('use far attenuation',bool(d['flags'] & 2))
            tag.tag.Save()
            after_materials=tag.tag.SelectField('Block:material info').Elements.Count
            if before_materials!=after_materials:
                raise ValueError('Native static-light writer changed the imported emissive material table')
        report['static_light_authoring'].append(dict(path=path,definitions=len(definitions),instances=len(instances),
            imported_material_rows_before=before_materials,imported_material_rows_after=after_materials,
            source_bsp=bsp['source_tag'],strategy='Foundry ScenarioStructureLightingInfoTag.build_tag; authored static baseline'))


def configure_scenario(paths, plan):
    from io_scene_foundry.managed_blam.scenario import ScenarioTag
    with ScenarioTag(path=plan['target']['scenario']) as tag:
        def references(block, field, expected):
            if not block.Elements.Count:
                for path in expected:
                    block.AddElement().SelectField(field).Path=tag._TagPath_from_string(path)
            actual=[e.SelectField(field).Path.RelativePathWithExtension.replace('\\','/') for e in block.Elements]
            if actual != expected:
                raise ValueError('Native scenario references differ from selected source plan: '+field)
        references(tag.block_bsps,'structure bsp',[b['destination'] for b in plan['bsps']])
        references(tag.block_structure_designs,'structure design',[d['destination'] for d in plan['structure_designs']])
        if not tag.block_skies.Elements.Count:
            for sky in plan['skies']:
                tag.add_new_sky(sky['destination'])
        references(tag.block_skies,'sky',[s['destination'] for s in plan['skies']])
        for element,bsp in zip(tag.block_bsps.Elements,plan['bsps']):
            element.SelectField('default sky').Value=bsp['default_sky']
            element.SelectField('size class').SetValue('1Meg_512x512')
            element.SelectField('custom gravity scale').Data=1.0
        for element,sky in zip(tag.block_skies.Elements,plan['skies']):
            for i,item in enumerate(element.SelectField('active on bsps').Items):
                item.IsSet=bool(sky['active_bsp_mask'] & (1<<i))
            for name in ('cloud scale','cloud speed','cloud direction'):
                element.SelectField(name).Data=0.0
        if plan.get('selection', {}).get('scope') == 'FULL_SCENARIO':
            from .native_zones import configure
            configure(tag, plan)
            zone = None
        elif not tag.block_zone_sets.Elements.Count:
            zone=tag.block_zone_sets.AddElement()
            zone.SelectField('name').SetStringData(plan['scenario']['zone_set'])
            for name in ('pvs index','hint previous zone set','audibility index'):
                zone.SelectField(name).Value=-1
        else:
            if tag.block_zone_sets.Elements.Count != 1:
                raise ValueError('Unexpected native zone sets')
            zone=tag.block_zone_sets.Elements[0]
            if zone.SelectField('name').GetStringData() != plan['scenario']['zone_set']:
                raise ValueError('Unexpected native zone-set identity')
            # Preserve PVS/audibility indices generated by Tool on the second
            # configuration pass. They are compiled target relationships.
        if zone is not None:
            for field,count in [('bsp zone flags',len(plan['bsps'])),('structure design zone flags',len(plan['structure_designs']))]:
                for i,item in enumerate(zone.SelectField(field).Items):
                    item.IsSet=i<count
        starts=tag.tag.SelectField('Block:player starting locations')
        if not starts.Elements.Count:
            tag.create_default_profile()
        starts.Elements[0].SelectField('position').Data=plan['scenario']['spawn']['position_world']
        starts.Elements[0].SelectField('facing').Data=plan['scenario']['spawn']['facing_degrees']
        tag.tag_has_changes=True
        tag.tag.Save()


def validate_scenario(plan, report):
    from io_scene_foundry.managed_blam.scenario import ScenarioTag
    from io_scene_foundry.managed_blam import Tag
    with ScenarioTag(path=plan['target']['scenario'],tag_must_exist=True) as tag:
        for field,block,expected in [('structure bsp',tag.block_bsps,[b['destination'] for b in plan['bsps']]),
            ('structure design',tag.block_structure_designs,[d['destination'] for d in plan['structure_designs']]),
            ('sky',tag.block_skies,[s['destination'] for s in plan['skies']])]:
            actual=[e.SelectField(field).Path.RelativePathWithExtension.replace('\\','/') for e in block.Elements]
            if actual != expected:
                raise ValueError('Native scenario readback mismatch: '+field)
        full = plan.get('selection', {}).get('scope') == 'FULL_SCENARIO'
        if full:
            from .native_zones import readback
            report['zone_set_readback'] = readback(tag, plan)
        zone=tag.block_zone_sets.Elements[plan['selection']['source_zone_index'] if full else 0]
        mask=sum(1<<i for i,v in enumerate(zone.SelectField('bsp zone flags').Items) if v.IsSet)
        if mask!=plan['scenario']['active_bsp_mask']:
            raise ValueError('Native zone set activates the wrong BSPs')
        start=tag.tag.SelectField('Block:player starting locations').Elements[0]
        position=list(start.SelectField('position').Data)
        if max(abs(a-b) for a,b in zip(position,plan['scenario']['spawn']['position_world']))>1e-4:
            raise ValueError('Native source-authored spawn position mismatch')
        report['scenario_readback']=dict(bsp_count=len(plan['bsps']),design_count=len(plan['structure_designs']),
            sky_count=len(plan['skies']),bsp_mask=mask,player_position=position)
    report['bsp_readback']=[]
    for bsp in plan['bsps']:
        with Tag(path=bsp['destination'],tag_must_exist=True) as tag:
            clusters=tag.tag.SelectField('Block:clusters').Elements
            instances=tag.tag.SelectField('Block:instanced geometry instances').Elements
            proofs={r['source_definition']:r for r in bsp['instance_plan'].get('unified_breakable_definitions',[])}
            split_count=sum(bool(proofs.get(p['source_definition'],{}).get('partition')) for p in bsp['instance_plan']['placements'])
            if not clusters.Count or instances.Count != len(bsp['instance_plan']['placements'])+split_count:
                raise ValueError(f'Native BSP cluster/instance count mismatch: {bsp["region"]}: {clusters.Count}/{instances.Count}')
            report['bsp_readback'].append(dict(path=bsp['destination'],clusters=clusters.Count,instances=instances.Count))
