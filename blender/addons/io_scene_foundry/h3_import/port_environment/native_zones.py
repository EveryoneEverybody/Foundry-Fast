"""Typed native zone-table authoring with source/target membership readback."""


def mask(field):
    return sum(1 << i for i, item in enumerate(field.Items) if item.IsSet)


def write_mask(field, value):
    items = list(field.Items)
    if value < 0 or value >> len(items):
        raise ValueError('Native bit field cannot represent source membership')
    for i, item in enumerate(items):
        item.IsSet = bool(value & (1 << i))


def configure(tag, plan):
    selection = plan['selection']
    zones = selection['zone_sets']
    designers = selection.get('designer_zones', [])
    block = tag.tag.SelectField('Block:designer zones')
    if block.Elements.Count == 0:
        for row in designers:
            block.AddElement().SelectField('name').SetStringData(row['name'])
    if [e.SelectField('name').GetStringData() for e in block.Elements] != [r['name'] for r in designers]:
        raise ValueError('Native designer zone identities differ from source')
    fresh = tag.block_zone_sets.Elements.Count == 0
    if fresh:
        for row in zones:
            element = tag.block_zone_sets.AddElement()
            element.SelectField('name').SetStringData(row['target_name'])
            for name in ('pvs index', 'audibility index'):
                element.SelectField(name).Value = -1
    if [e.SelectField('name').GetStringData() for e in tag.block_zone_sets.Elements] != [r['target_name'] for r in zones]:
        raise ValueError('Native zone identities/order differ from source')
    for element, row in zip(tag.block_zone_sets.Elements, zones):
        element.SelectField('name string').SetStringData(row['target_name'])
        write_mask(element.SelectField('bsp zone flags'), row['target_bsp_mask'])
        write_mask(element.SelectField('structure design zone flags'), row['target_design_mask'])
        # Paired H3/Reach schema has the same three named authored zone flags.
        flags = int(row['source_fields'].get('flags', '0'))
        if flags & ~7:
            raise ValueError('Unmapped source zone-set flags')
        write_mask(element.SelectField('flags'), flags)
        element.SelectField('hint previous zone set').Value = row['hint_previous_zone_set']
        for name in ('required designer zones', 'forbidden designer zones'):
            value = int(row['source_fields'].get(name, '0'))
            if value >> len(designers):
                raise ValueError('Source zone references absent designer zone')
            write_mask(element.SelectField(name), value)
        # Cinematic resources are deferred; retaining source bit indices in an
        # empty native cinematic palette would create invalid references.
        write_mask(element.SelectField('cinematic zones'), 0)
    return readback(tag, plan)


def readback(tag, plan):
    zones = plan['selection']['zone_sets']
    if tag.block_zone_sets.Elements.Count != len(zones):
        raise ValueError('Native authored zone-set count differs')
    results = []
    for element, row in zip(tag.block_zone_sets.Elements, zones):
        name = element.SelectField('name').GetStringData()
        bsp = mask(element.SelectField('bsp zone flags'))
        design = mask(element.SelectField('structure design zone flags'))
        if (name, bsp, design) != (row['target_name'], row['target_bsp_mask'], row['target_design_mask']):
            raise ValueError('Native zone-set membership differs: '+str(row['source_index']))
        previous = element.SelectField('hint previous zone set').Value
        if previous != row['hint_previous_zone_set']:
            raise ValueError('Native previous-zone hint differs: '+name)
        for field in ('required designer zones', 'forbidden designer zones', 'flags'):
            if mask(element.SelectField(field)) != int(row['source_fields'].get(field, '0')):
                raise ValueError('Native zone-set flags differ: '+name+' '+field)
        results.append(dict(source_index=row['source_index'], source_name=row['source_name'],
            source_bsp_mask=row['source_bsp_mask'], target_index=row['target_index'], target_name=name,
            target_bsp_mask=bsp, target_design_mask=design, hint_previous_zone_set=previous,
            native_pvs_index=int(element.SelectField('pvs index').Value),
            native_audibility_index=int(element.SelectField('audibility index').Value),
            source_cinematic_mask=int(row['source_fields'].get('cinematic zones', '0')),
            cinematic_status='DEFERRED', membership_status='VERIFIED'))
    return results
