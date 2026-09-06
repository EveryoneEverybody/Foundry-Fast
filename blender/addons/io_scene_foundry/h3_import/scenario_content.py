"""Pure planning for source scenario placements and readable authored content.

No runtime activation, ownership or AI execution is inferred from these records.
"""
from pathlib import PurePosixPath
from .scenario_scene import FieldIndex, numbers
from .scenario_inspection import relative_path

CATEGORIES = {
    'scenery': 'scenery', 'machines': 'machine', 'controls': 'control',
    'crates': 'crate', 'vehicles': 'vehicle', 'weapons': 'weapon',
    'equipment': 'equipment', 'bipeds': 'biped', 'giants': 'giant',
    'effect scenery': 'effect scenery', 'sound scenery': 'sound scenery',
    'light volumes': 'light volumes', 'terminals': 'terminal',
}
CONTENT_ROOTS = set(CATEGORIES) | {v + ' palette' for v in CATEGORIES.values()} | {
    'object names', 'editor folders', 'trigger volumes', 'player starting locations',
    'cutscene flags', 'cutscene camera points', 'squads', 'squad groups', 'zones',
    'ai objectives', 'designer zones', 'scripting data', 'character palette',
}

def numeric(value, size):
    if not isinstance(value, dict) or 'values' not in value:
        raise ValueError('Typed source coordinates unavailable; re-extract with the current inspector')
    return list(numbers(value['values'], size))

def tag_reference(value):
    if not isinstance(value, dict) or not value.get('path') or not value.get('extension'):
        raise ValueError('Missing source palette tag reference')
    return relative_path(value['path'].replace('\\', '/') + '.' + value['extension']).as_posix()

class ContentIndex(FieldIndex):
    def struct(self, parent, name):
        row = self.one(parent, name, 'struct', required=False)
        return row['address'] if row else None

    def metadata(self, parent):
        # Full data, including large node-orientation blocks, stays in inventory.
        return {r['name']: r['value'] for r in self.children.get(parent, []) if r['kind'] == 'value' and r['name']}

    def scalar(self, parent, name, default=0.):
        value = self.value(parent, name)
        return numeric(value, 1)[0] if value is not None else default

def plan(data):
    index = ContentIndex(data, CONTENT_ROOTS)
    result = {'placements': [], 'groups': [], 'overlays': [], 'diagnostics': []}
    def warn(address, message):
        result['diagnostics'].append({'address': address, 'reason': str(message)})
    def group(key, name, parent, address, **extra):
        result['groups'].append(dict(key=key, name=name, parent=parent, address=address, metadata=index.metadata(address), **extra))
        return key
    def marker(kind, parent, address, name, position, **extra):
        result['overlays'].append(dict(kind=kind, parent=parent, address=address, name=name,
            position=position, metadata=index.metadata(address), **extra))
    names = {i: index.value(p, 'name', '') for i, p in index.elements('', 'object names')}
    folders = dict(index.elements('', 'editor folders'))
    for i, p in folders.items():
        parent = index.value(p, 'parent folder', -1)
        group(f'folder:{i}', index.value(p, 'name') or f'Folder {i}', f'folder:{parent}' if parent in folders else 'Objects', p)
    for category, palette_name in CATEGORIES.items():
        palettes = dict(index.elements('', palette_name + ' palette'))
        for i, p in index.elements('', category):
            ob = index.struct(p, 'object data')
            if ob is None:
                warn(p, 'Missing object placement data'); continue
            palette = index.value(p, 'type', -1)
            identity = index.value(p, 'name', -1)
            permutation = index.struct(p, 'permutation data')
            parent = index.struct(ob, 'parent id')
            source = None
            diagnostics = []
            try:
                source = tag_reference(index.value(palettes.get(palette), 'name'))
            except ValueError as error:
                diagnostics.append(str(error))
            name = names.get(identity) or (PurePosixPath(source).stem if source else category.rstrip('s')) + f' [{i}]'
            metadata = {'placement': index.metadata(p), 'object': index.metadata(ob),
                        'permutation': index.metadata(permutation), 'parent': index.metadata(parent)}
            for row in index.children[p]:
                if row['kind'] == 'struct' and row['address'] not in {ob, permutation, parent}:
                    metadata[row['name']] = index.metadata(row['address'])
            row = dict(category=category, index=i, address=p, name=name, name_index=identity,
                palette_index=palette, source_tag=source, variant=index.value(permutation, 'variant name', '') or '',
                folder=index.value(ob, 'editor folder', -1), metadata=metadata, diagnostics=diagnostics,
                parent_name_index=index.value(parent, 'parent object', -1),
                parent_marker=index.value(parent, 'parent marker', ''), connection_marker=index.value(parent, 'connection marker', ''))
            try:
                row['position'] = index.point(ob, 'position')
                row['rotation'] = numeric(index.value(ob, 'rotation'), 3)
                row['source_scale'] = index.scalar(ob, 'scale')
                # Same zero-as-default placement convention as Reach ScenarioObject.
                row['scale'] = row['source_scale'] if row['source_scale'] != 0 else 1.
            except (ValueError, KeyError, TypeError) as error:
                diagnostics.append(str(error)); row['position'] = None
            if index.elements(ob, 'node orientations'):
                diagnostics.append('Stored node pose retained at source address; visualization uses the model rest pose')
            if row['parent_name_index'] != -1:
                diagnostics.append('Parent/marker attachment retained; unresolved attachment is not drawn at a guessed world position')
                row['position'] = None
            result['placements'].append(row)
    for category, facing, size in [('player starting locations', 'facing', 1), ('cutscene flags', 'facing', 2), ('cutscene camera points', 'orientation', 3)]:
        for i, p in index.elements('', category):
            try:
                rotation = numeric(index.value(p, facing), size)
                if size == 1: rotation += [index.scalar(p, 'pitch'), 0.]
                elif size == 2: rotation += [0.]
                marker(category, category.title(), p, index.value(p, 'name') or f'{category} [{i}]', index.point(p, 'position'), rotation=rotation)
            except (ValueError, KeyError, TypeError) as error: warn(p, error)
    for i, p in index.elements('', 'trigger volumes'):
        try:
            if index.value(p, 'object name', -1) != -1:
                raise ValueError('Object-relative trigger attachment retained, not drawn')
            marker('trigger volumes', 'Trigger Volumes', p, index.value(p, 'name') or f'trigger [{i}]', index.point(p, 'position'),
                forward=numeric(index.value(p, 'forward'),3), up=numeric(index.value(p, 'up'),3), extents=index.point(p,'extents'))
        except (ValueError, KeyError, TypeError) as error: warn(p,error)
    squad_groups = dict(index.elements('', 'squad groups'))
    for i, p in squad_groups.items():
        parent = index.value(p, 'parent', -1)
        group(f'squad-group:{i}', index.value(p,'name') or f'Squad group {i}', f'squad-group:{parent}' if parent in squad_groups else 'AI / Squads', p)
    for i, p in index.elements('', 'squads'):
        parent = index.value(p, 'parent', -1)
        key = group(f'squad:{i}', index.value(p,'name') or f'Squad {i}', f'squad-group:{parent}' if parent in squad_groups else 'AI / Squads', p)
        for team_i, team in index.elements(p, 'fire-teams'):
            team_key = group(f'{key}/team:{team_i}', f'Fire team {team_i}', key, team)
            for start_i, start in index.elements(team, 'starting locations'):
                try:
                    if index.value(start,'reference frame') != -1: raise ValueError('Squad start reference frame unresolved')
                    rotation=numeric(index.value(start,'facing (yaw, pitch)'),2)+[index.scalar(start,'roll')]
                    marker('squad starts',team_key,start,index.value(start,'name') or f'Start {start_i}',index.point(start,'position'),rotation=rotation)
                except (ValueError,KeyError,TypeError) as error: warn(start,error)
    for i,p in index.elements('', 'zones'):
        key=group(f'zone:{i}',index.value(p,'name') or f'Zone {i}','AI / Zones',p)
        for area_i,area in index.elements(p,'areas'):
            area_key=group(f'{key}/area:{area_i}',index.value(area,'name') or f'Area {area_i}',key,area)
            try:
                if index.value(area,'runtime reference frame') != -1: raise ValueError('Area reference frame unresolved')
                marker('area mean',area_key,area,'Source mean',index.point(area,'runtime relative mean point'))
            except (ValueError,KeyError,TypeError) as error: warn(area,error)
    for i,p in index.elements('', 'scripting data'):
        for set_i,point_set in index.elements(p,'point sets'):
            group(f'point-set:{i}:{set_i}',index.value(point_set,'name') or f'Point set {set_i}','Script Point Sets',point_set)
    for i,p in index.elements('', 'ai objectives'):
        key=group(f'objective:{i}',index.value(p,'name') or f'Objective {i}','AI / Objectives',p)
        for task_i,task in index.elements(p,'tasks'):
            task_key=group(f'{key}/task:{task_i}',index.value(task,'name') or f'Task {task_i}',key,task,
                area_references=[index.metadata(a) for _,a in index.elements(task,'areas')])
            for direction_i,direction in index.elements(task,'direction'):
                try:
                    if any(index.value(direction,f'reference frame{n}') != -1 for n in (0,1)):
                        raise ValueError('Objective direction reference frame unresolved')
                    marker('objective direction',task_key,direction,f'Direction {direction_i}',index.point(direction,'point0'),end=index.point(direction,'point1'))
                except (ValueError,KeyError,TypeError) as error: warn(direction,error)
    for i,p in index.elements('', 'designer zones'):
        references = {r['name']:[index.metadata(v) for _,v in index.elements(p,r['name'])] for r in index.children[p] if r['kind']=='block'}
        group(f'designer-zone:{i}',index.value(p,'name') or f'Designer zone {i}','AI / Designer Zones',p,palette_references=references)
    return result
