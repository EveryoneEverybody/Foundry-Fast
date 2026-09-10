"""Conservative read-only parameter check for retained Reach MAX-light records.

This optional check refuses ambiguous/missing records. It does not claim pixel
acceptance or infer light contribution from the presence of an emitter record.
"""
import math
import mmap
import struct


def near(a,b): return math.isclose(a,b,rel_tol=3e-5,abs_tol=1e-6)


def verify(blob, probe):
    d=probe['definition_input']; ip=probe['instance']; expected=probe['expected_world']
    with open(blob,'rb') as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
        pos=struct.pack('<3f',*ip['origin']);p=data.find(pos)
        if p<40 or data.find(pos,p+1)>=0:raise ValueError('Missing/ambiguous solver instance origin')
        instance=struct.unpack_from('<13fIIfI',data,p-40)
        if instance[13]&255 != 23 or instance[14]!=ip['bungie light type']:
            raise ValueError('Unsupported solver instance format/type')
        if not all(near(a,b) for a,b in zip(instance[1:4],ip['forward'])) or not all(near(a,b) for a,b in zip(instance[7:10],ip['up'])):
            raise ValueError('Solver instance transform mismatch')
        hits=[];at=0;attempts=0;needle=struct.pack('<f',d['intensity'])
        while True:
            at=data.find(needle,at)
            if at<0:break
            attempts+=1
            if attempts>1000000:raise ValueError('Solver record search too ambiguous')
            if 28<=at and at+40<=len(data):
                row=struct.unpack_from('<4i7fi5f',data,at-28)
                rgb=[max(0,min(1,c))**2.2 for c in d['color']]
                if (row[0]==d['type'] and row[1]==int(d['shape']!=0) and row[2]==int(bool(d['flags']&4))
                    and all(near(a,b) for a,b in zip(row[4:7],rgb)) and near(row[16],d['aspect'])
                    and d['type']==1 and near(row[8],math.radians(d['hotspot size'])/2)
                    and near(row[9],math.radians(d['hotspot cutoff size'])/2)):
                    hits.append((at-28,row))
            at+=1
        if len(hits)!=1:raise ValueError('Missing/ambiguous matching solver definition (spot probe required)')
        off,row=hits[0]
        if not all(near(a,b) for a,b in zip(row[14:16],expected['far_attenuation'])):
            raise ValueError(f"Effective solver range mismatch: {row[14:16]} expected {expected['far_attenuation']}")
        if not near(row[12],expected['near_attenuation'][0]):raise ValueError('Effective solver near start mismatch')
        return dict(status='MATCHING_SOLVER_PARAMETERS_VERIFIED',blob=str(blob),definition_offset=off,
            instance_offset=p-40,definition_handle=instance[13],intensity=row[7],far_world=list(row[14:16]),
            near_world=list(row[12:14]),expected_postprocessed_near=expected['near_attenuation'],
            note='MAX constructor stores near start in both slots; this probe does not assert near-end preservation or visible contribution.')
