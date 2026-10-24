#!/usr/bin/env python3
"""Author or export a Blender world for the native Flexscript simulator.

Run with Blender's Python, not the system interpreter. All distances are metres,
Z is up. Tagged mesh objects provide rigid box colliders independently of their
render geometry. Re-export --blend after editing the saved source in Blender.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]


def publish(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.'+path.name, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def material(name, color):
    result = bpy.data.materials.new(name)
    result.diffuse_color = (*color, 1)
    result.use_nodes = True
    shader = result.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = 0.78
    return result


def box(name, centre, size, surface, collision=True, bevel=0, cutaway=False):
    bpy.ops.mesh.primitive_cube_add(size=1, location=centre)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(surface)
    obj['sim_collision'] = collision
    obj['sim_cutaway'] = cutaway
    if bevel:
        modifier = obj.modifiers.new('Soft edges', 'BEVEL')
        modifier.width = bevel
        modifier.segments = 3
    return obj


def table(name, x, y, width, depth, height, wood, legs):
    box(name+'.top', (x, y, height-0.025), (width, depth, 0.05), wood, bevel=0.012)
    for i, (dx, dy) in enumerate(((-1, -1), (-1, 1), (1, -1), (1, 1))):
        box(name+f'.leg-{i+1}', (x+dx*(width/2-0.07), y+dy*(depth/2-0.07), (height-0.05)/2),
            (0.065, 0.065, height-0.05), legs, bevel=0.008)


def chair(name, x, y, facing, wood, fabric):
    box(name+'.seat', (x, y, 0.44), (0.42, 0.42, 0.055), fabric, bevel=0.018)
    # The back faces away from the table. Legs leave genuine empty space.
    dx, dy = facing
    box(name+'.back', (x-dx*0.185, y-dy*0.185, 0.69),
        (0.05 if dx else 0.42, 0.05 if dy else 0.42, 0.50), wood, bevel=0.015)
    for i, (a, b) in enumerate(((-1, -1), (-1, 1), (1, -1), (1, 1))):
        box(name+f'.leg-{i+1}', (x+a*0.16, y+b*0.16, 0.207), (0.042, 0.042, 0.414), wood, bevel=0.006)


def floor_text(text, x, y, surface, size=0.20):
    bpy.ops.object.text_add(location=(x, y, 0.008))
    obj = bpy.context.object
    obj.name = 'Label.'+text
    obj.data.body = text
    obj.data.size = size
    obj.data.align_x = 'CENTER'
    obj.data.materials.append(surface)
    bpy.ops.object.convert(target='MESH')


def generate():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1
    root = bpy.data.objects.new('SIM_WORLD', None)
    scene.collection.objects.link(root)
    root['sim_bounds'] = [-1.0, -3.0, 7.4, 3.0]
    root['sim_spawn'] = [0.0, 0.0, 0.0]
    root['sim_title'] = 'Three-room apartment'
    wall = material('Warm plaster', (0.79, 0.76, 0.66))
    trim = material('Ivory trim', (0.92, 0.87, 0.73))
    oak = material('Honey oak', (0.61, 0.39, 0.19))
    dark = material('Dark wood', (0.20, 0.14, 0.10))
    teal = material('Couch teal', (0.12, 0.43, 0.44))
    cushion = material('Sage cushions', (0.30, 0.58, 0.49))
    terracotta = material('Terracotta', (0.66, 0.26, 0.12))
    green = material('Leaves', (0.16, 0.40, 0.14))
    brass = material('Brass', (0.77, 0.57, 0.23))
    rug = material('Living rug', (0.62, 0.39, 0.27))
    tile = material('Hall stone', (0.57, 0.62, 0.61))
    label = material('Floor lettering', (0.28, 0.24, 0.20))
    # The runtime creates one physical floor. These surfaces are visual only.
    box('Hall.floor', (3.7, 0, -0.016), (1.4, 6, 0.032), tile, False)
    for room, lo, hi in (('Living', -1, 3), ('Dining', 4.4, 7.4)):
        for strip in range(20):
            surface = material(room+f'.oak-{strip}', (0.60+0.018*(strip % 3), 0.43+0.012*(strip % 3), 0.28))
            box(room+f'.floor-{strip}', ((lo+hi)/2, -3+(strip+0.5)*0.30, -0.016), (hi-lo, 0.297, 0.032), surface, False)
    box('Living.rug', (1.25, -1.60, 0.003), (2.15, 1.45, 0.006), rug, False, bevel=0.02)
    for edge, centre, size in (
        ('west', (-1, 0, 1.25), (0.12, 6.12, 2.5)),
        ('east', (7.4, 0, 1.25), (0.12, 6.12, 2.5)),
        ('south', (3.2, -3, 1.25), (8.4, 0.12, 2.5)),
        ('north', (3.2, 3, 1.25), (8.4, 0.12, 2.5)),
    ):
        box('Wall.outer-'+edge, centre, size, wall, cutaway=True)
    for x, room in ((3.0, 'living'), (4.4, 'dining')):
        # 1.30 m opening, 2.10 m headroom. Both lintels remain physical.
        for sign in (-1, 1):
            box('Wall.'+room+f'-{sign}', (x, sign*1.825, 1.25), (0.12, 2.35, 2.5), wall, cutaway=True)
            box('Trim.'+room+f'-{sign}', (x, sign*0.67, 1.05), (0.16, 0.045, 2.10), trim, cutaway=True)
        box('Wall.'+room+'-lintel', (x, 0, 2.30), (0.12, 1.30, 0.4), wall, cutaway=True)
    # Sofa body is several solids rather than a room-sized furniture bound.
    box('Sofa.base', (0.65, 2.18, 0.21), (2.25, 0.82, 0.32), teal, bevel=0.06)
    box('Sofa.back', (0.65, 2.55, 0.56), (2.25, 0.17, 0.72), teal, bevel=0.055)
    for x in (-0.43, 1.73):
        box('Sofa.arm'+str(x), (x, 2.18, 0.46), (0.16, 0.82, 0.45), teal, bevel=0.045)
    for x in (0.10, 0.65, 1.20):
        box('Sofa.cushion'+str(x), (x, 2.12, 0.40), (0.52, 0.61, 0.12), cushion, False, bevel=0.05)
    table('Coffee', 1.35, -1.60, 1.15, 0.65, 0.46, oak, dark)
    table('Dining', 5.90, -1.65, 1.60, 1.0, 0.78, oak, dark)
    for name, x, y, facing in (
        ('south', 5.9, -2.50, (0, 1)), ('north', 5.9, -0.79, (0, -1)),
        ('west', 4.83, -1.65, (1, 0)), ('east', 6.97, -1.65, (-1, 0)),
    ):
        chair('Chair.'+name, x, y, facing, oak, cushion)
    table('Hall.console', 3.7, 2.4, 0.90, 0.35, 0.72, oak, dark)
    # A shallow bookcase with individually solid shelves and side panels.
    for z in (0.08, 0.48, 0.88, 1.28, 1.65):
        box('Bookcase.shelf'+str(z), (-0.70, -1.75, z), (0.38, 1.50, 0.045), oak, bevel=0.008)
    for y in (-2.48, -1.02):
        box('Bookcase.side'+str(y), (-0.70, y, 0.85), (0.38, 0.045, 1.65), oak)
    for i in range(12):
        surface = (teal, terracotta, brass, green)[i % 4]
        box('Book.'+str(i), (-0.70, -2.30+i*0.09, 0.64), (0.25, 0.06, 0.26+0.02*(i % 3)), surface, False)
    # Rounded plant pots retain a conservative box collider at their base.
    for name, x, y in (('Living', 2.48, 2.36), ('Dining', 6.85, 2.30)):
        box('Plant.'+name+'.pot', (x, y, 0.16), (0.32, 0.32, 0.32), terracotta, bevel=0.08)
        for i in range(7):
            angle = i*2*math.pi/7
            bpy.ops.mesh.primitive_uv_sphere_add(segments=10, ring_count=6, radius=1,
                location=(x+0.11*math.cos(angle), y+0.11*math.sin(angle), 0.50+0.035*(i % 3)))
            leaf = bpy.context.object
            leaf.name = 'Plant.'+name+f'.leaf-{i}'
            leaf.scale = (0.09, 0.10, 0.25)
            leaf.data.materials.append(green)
    floor_text('LIVING', 0.9, 0.85, label)
    floor_text('HALL', 3.7, 0.85, label, 0.15)
    floor_text('DINING', 5.9, 0.85, label)
    # Authoring camera and lights are for Blender inspection only. The native
    # renderer always uses its existing observer/TCP camera transforms.
    bpy.ops.object.camera_add(location=(11, -10, 12))
    camera = bpy.context.object
    camera.name = 'Authoring overview (not a robot sensor)'
    camera.rotation_euler = (Vector((3.2, 0, 0))-camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera = camera
    bpy.ops.object.light_add(type='AREA', location=(3, 0, 7))
    bpy.context.object.data.energy = 1800
    bpy.context.object.data.shape = 'DISK'
    bpy.context.object.data.size = 10
    scene.world.color = (0.3, 0.3, 0.3)
    for area in bpy.context.screen.areas if bpy.context.screen else ():
        if area.type == 'VIEW_3D':
            area.spaces.active.region_3d.view_location = (3.2, 0, 0)
            area.spaces.active.region_3d.view_distance = 12


def export_world(output, source):
    root = bpy.data.objects.get('SIM_WORLD')
    if root is None:
        raise ValueError('missing SIM_WORLD with sim_bounds and sim_spawn')
    bounds, spawn = list(root['sim_bounds']), list(root['sim_spawn'])
    title = root['sim_title']
    if len(bounds) != 4 or len(spawn) != 3 or not all(math.isfinite(v) and abs(v) <= 100 for v in bounds+spawn):
        raise ValueError('invalid world bounds/spawn')
    if not (bounds[0] < spawn[0] < bounds[2] and bounds[1] < spawn[1] < bounds[3]):
        raise ValueError('spawn must be inside world bounds')
    encoded_title = title.encode('ascii')
    if not 0 < len(encoded_title) < 64:
        raise ValueError('world title must be 1..63 ASCII characters')
    colliders, full, overview = [], bytearray(), bytearray()
    graph = bpy.context.evaluated_depsgraph_get()
    for obj in sorted(bpy.context.scene.objects, key=lambda o: o.name):
        if obj.type != 'MESH' or obj.hide_render:
            continue
        matrix = obj.matrix_world
        if obj.get('sim_collision', False):
            location, rotation, scale = matrix.decompose()
            euler = rotation.to_euler('XYZ')
            reconstructed = Matrix.LocRotScale(location, rotation, scale)
            shear = max(abs(matrix[i][j]-reconstructed[i][j]) for i in range(4) for j in range(4))
            if abs(euler.x) > 1e-5 or abs(euler.y) > 1e-5 or any(v <= 0 for v in scale) or shear > 1e-5:
                raise ValueError(obj.name+': box collider supports positive scale and Z rotation without shear')
            corners = [Vector(v) for v in obj.bound_box]
            lo = [min(v[k] for v in corners) for k in range(3)]
            hi = [max(v[k] for v in corners) for k in range(3)]
            centre = list(matrix @ Vector([(a+b)/2 for a, b in zip(lo, hi)]))
            half = [(b-a)*scale[k]/2 for k, (a, b) in enumerate(zip(lo, hi))]
            name = obj.name.encode('ascii')
            if len(name) > 47 or not all(math.isfinite(v) and 0 < v <= 100 for v in half):
                raise ValueError('invalid box collider '+obj.name)
            colliders.append(dict(id=obj.name, position=centre, halfSize=half, yawRadians=euler.z))
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            normal_matrix = matrix.to_3x3().inverted().transposed()
            for triangle in mesh.loop_triangles:
                normal = (normal_matrix @ triangle.normal).normalized()
                surface = mesh.materials[triangle.material_index] if mesh.materials else None
                color = list(surface.diffuse_color[:3]) if surface else [0.7]*3
                for index in triangle.vertices:
                    position = list(matrix @ mesh.vertices[index].co)
                    full.extend(struct.pack('<9f', *position, *normal, *color))
                    if obj.get('sim_cutaway', False):
                        position[2] = min(position[2], 0.38)
                    overview.extend(struct.pack('<9f', *position, *normal, *color))
        finally:
            evaluated.to_mesh_clear()
    if not 1 <= len(colliders) <= 160 or not 3 <= len(full)//36 <= 1000000:
        raise ValueError('world exceeds collider/vertex budget')
    header = bytearray(256)
    struct.pack_into('<8sQQQ', header, 0, b'PBENV001', len(colliders), len(full)//36, len(overview)//36)
    struct.pack_into('<4d3d', header, 64, *bounds, *spawn)
    header[128:128+len(encoded_title)] = encoded_title
    records = bytearray()
    for collider in colliders:
        record = bytearray(128)
        name = collider['id'].encode('ascii')
        record[:len(name)] = name
        struct.pack_into('<7d', record, 48, *collider['position'], *collider['halfSize'], collider['yawRadians'])
        records.extend(record)
    data = header+records+full+overview
    publish(output/'apartment.bin', data)
    manifest = dict(schema='puppybot.environment.v1', title=title, units='metres', up='Z',
        bounds=bounds, spawn=spawn, source=str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source),
        sourceSha256=hashlib.sha256(source.read_bytes()).hexdigest(), binarySha256=hashlib.sha256(data).hexdigest(),
        vertices=len(full)//36, colliders=colliders, cameraSensors=['tcp'],
        physics='Static furniture OBBs; decorative books, leaves, cushions and rugs are visual only.',
        overview='Existing world observer uses cutaway walls; robot RGB views use full-height geometry.')
    publish(output/'scene.json', (json.dumps(manifest, indent=2)+'\n').encode())
    # A portable interchange artifact alongside the native packed mesh. Blender
    # converts Z-up to glTF Y-up itself; the native binary stays in Z-up metres.
    bpy.ops.export_scene.gltf(filepath=str(output/'apartment.glb'), export_format='GLB',
        export_cameras=False, export_lights=False, export_extras=True)
    print(f'Exported {len(colliders)} colliders, {len(full)//36} vertices to {output}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--generate', action='store_true', help='create the owned apartment source')
    group.add_argument('--blend', type=Path, help='re-export an edited Blender source')
    parser.add_argument('--output', type=Path, default=ROOT/'build/flex/sim/environments/apartment')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if args.generate:
        source = ROOT/'models/environments/apartment/apartment.blend'
        if source.exists():
            raise ValueError('source already exists; use --blend to export edits without regenerating it')
        generate()
        source.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
    else:
        source = args.blend.resolve()
        bpy.ops.wm.open_mainfile(filepath=str(source))
    export_world(args.output.resolve(), source)


if __name__ == '__main__':
    main()
