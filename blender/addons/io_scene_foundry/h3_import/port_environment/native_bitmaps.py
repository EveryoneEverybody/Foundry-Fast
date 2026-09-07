"""Pixel-preserving cubemap atlas reorganization for Reach's TIFF authoring."""
CUBE_LAYOUT='reach_cross_frblud_v1'
PIXEL_EXPORT='standard_texture_pixels_v1'
# Reach/Foundry BitmapTag.cubemap_to_equirectangular's 4x3 source layout.
# Keys retain the source DDS (+X,-X,+Y,-Y,+Z,-Z) identity.
REACH_CELLS=((1,1),(3,1),(0,0),(0,2),(0,1),(2,1))


def author_cube(source,layout):
    import bpy
    import numpy as np
    if layout['layout']!='directx_cross_4x3' or layout['face_order']!=['+X','-X','+Y','-Y','+Z','-Z']:
        raise ValueError('Unverified source cube face layout')
    width,height=source.size
    size=width//4
    if size*4!=width or size*3!=height:raise ValueError('Invalid cube source dimensions')
    pixels=np.empty(width*height*4,dtype=np.float32)
    source.pixels.foreach_get(pixels)
    original=pixels.reshape(height,width,4)[::-1]
    output=np.zeros_like(original)
    for (sx,sy),(dx,dy) in zip(layout['cells'],REACH_CELLS):
        output[dy*size:(dy+1)*size,dx*size:(dx+1)*size]=original[sy*size:(sy+1)*size,sx*size:(sx+1)*size]
    name=source.name
    source.name=name+'_source_atlas'
    image=bpy.data.images.new(name,width=width,height=height,alpha=True)
    image.colorspace_settings.name=source.colorspace_settings.name
    image.alpha_mode='CHANNEL_PACKED'
    image.pixels.foreach_set(np.ascontiguousarray(output[::-1]).ravel())
    for key in source.keys():image[key]=source[key]
    image['h3_native_cube_layout']=CUBE_LAYOUT
    image.pack()
    return image
