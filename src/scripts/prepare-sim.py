#!/usr/bin/env python3
"""Pack the owned URDF/glTF assets for the native Flexscript simulator.

Only asset conversion happens here. Joint transforms, controller execution,
world stepping, contact physics and rendering run in the compiled executable.
"""
import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def publish(path, data):
    # Running simulators mmap the asset. Replace its inode after the complete
    # write so a rebuild cannot truncate an active mapping.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.'+path.name+'-', delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o644)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def identity():
    return [float(i % 5 == 0) for i in range(16)]


def multiply(a, b):
    return [sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
            for col in range(4) for row in range(4)]


def translation(xyz):
    m = identity()
    m[12:15] = xyz
    return m


def rotation(axis, angle):
    x, y, z = axis
    c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return [t*x*x+c, t*x*y+s*z, t*x*z-s*y, 0,
            t*x*y-s*z, t*y*y+c, t*y*z+s*x, 0,
            t*x*z+s*y, t*y*z-s*x, t*z*z+c, 0, 0, 0, 0, 1]


def transform(xyz, rpy):
    m = translation(xyz)
    for axis, angle in zip(((0, 0, 1), (0, 1, 0), (1, 0, 0)), reversed(rpy)):
        m = multiply(m, rotation(axis, angle))
    return m


def numbers(text, default):
    result = list(map(float, text.split())) if text else list(default)
    if len(result) != len(default) or not all(map(math.isfinite, result)):
        raise ValueError('invalid model vector')
    return result


def origin(element):
    e = element.find('origin')
    return identity() if e is None else transform(numbers(e.get('xyz'), (0, 0, 0)), numbers(e.get('rpy'), (0, 0, 0)))


def point(m, p, w=1):
    return [sum(m[k*4+i]*p[k] for k in range(3)) + m[12+i]*w for i in range(3)]


def node_matrix(node):
    if 'matrix' in node:
        return node['matrix']
    x, y, z, w = node.get('rotation', (0, 0, 0, 1))
    m = [1-2*(y*y+z*z), 2*(x*y+z*w), 2*(x*z-y*w), 0,
         2*(x*y-z*w), 1-2*(x*x+z*z), 2*(y*z+x*w), 0,
         2*(x*z+y*w), 2*(y*z-x*w), 1-2*(x*x+y*y), 0, 0, 0, 0, 1]
    for col, scale in enumerate(node.get('scale', (1, 1, 1))):
        for row in range(3):
            m[col*4+row] *= scale
    m[12:15] = node.get('translation', (0, 0, 0))
    return m


def triangles(path):
    doc = json.loads(path.read_text())
    buffers = []
    for b in doc['buffers']:
        uri = b['uri']
        raw = base64.b64decode(uri.split(',', 1)[1]) if uri.startswith('data:') else (path.parent / uri).read_bytes()
        if len(raw) != b['byteLength']:
            raise ValueError(f'{path}: buffer length mismatch')
        buffers.append(raw)

    def accessor(index):
        a = doc['accessors'][index]
        if 'sparse' in a or a.get('normalized'):
            raise ValueError(f'{path}: unsupported accessor')
        v = doc['bufferViews'][a['bufferView']]
        count = {'SCALAR': 1, 'VEC3': 3}[a['type']]
        fmt = '<' + {5121: 'B', 5123: 'H', 5125: 'I', 5126: 'f'}[a['componentType']] * count
        stride = v.get('byteStride', struct.calcsize(fmt))
        start = v.get('byteOffset', 0) + a.get('byteOffset', 0)
        return [struct.unpack_from(fmt, buffers[v['buffer']], start + i*stride) for i in range(a['count'])]

    def visit(index, parent):
        node = doc['nodes'][index]
        m = multiply(parent, node_matrix(node))
        if 'mesh' in node:
            for prim in doc['meshes'][node['mesh']]['primitives']:
                if prim.get('mode', 4) != 4:
                    raise ValueError(f'{path}: non-triangle mesh')
                positions = accessor(prim['attributes']['POSITION'])
                normals = accessor(prim['attributes']['NORMAL']) if 'NORMAL' in prim['attributes'] else None
                indices = [v[0] for v in accessor(prim['indices'])] if 'indices' in prim else list(range(len(positions)))
                if len(indices) % 3:
                    raise ValueError(f'{path}: incomplete triangle')
                material = doc.get('materials', [])[prim['material']] if 'material' in prim else {}
                color = material.get('pbrMetallicRoughness', {}).get('baseColorFactor', (0.7, 0.7, 0.7, 1))[:3]
                for at in range(0, len(indices), 3):
                    points = [point(m, positions[i]) for i in indices[at:at+3]]
                    u, v = [[p[j]-points[0][j] for j in range(3)] for p in points[1:]]
                    face = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
                    for i, p in zip(indices[at:at+3], points):
                        # The owned exports use rigid node transforms.
                        n = point(m, normals[i], 0) if normals else face
                        length = math.sqrt(sum(x*x for x in n)) or 1
                        yield p, [x/length for x in n], color
        for child in node.get('children', []):
            yield from visit(child, m)

    for index in doc['scenes'][doc.get('scene', 0)]['nodes']:
        yield from visit(index, identity())


def prepare(output):
    model = ROOT / 'models/puppybot'
    urdf = model / 'final2/urdf/final2.urdf'
    profile_path = model / 'robotdreams.json'
    profile = json.loads(profile_path.read_text())
    robot = ET.parse(urdf).getroot()
    links = {e.get('name'): e for e in robot.findall('link')}
    children = {}
    child_names = set()
    for joint in robot.findall('joint'):
        children.setdefault(joint.find('parent').get('link'), []).append(joint)
        child_names.add(joint.find('child').get('link'))
    roots = set(links) - child_names
    if len(roots) != 1:
        raise ValueError('URDF must have one root')
    groups, geometry, link_frames, visited, mesh_cache = [], [], {}, set(), {}
    colliders = []
    sources = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (urdf, profile_path)}
    mapping = profile['analyticToUrdf']['joints']
    arm = {mapping[name]['joint']: (i, mapping[name]['scale'], mapping[name]['offset'])
           for i, name in enumerate(('yaw', 'shoulder', 'elbow', 'wrist'))}

    def group(parent, m, joint=None):
        control, scale, offset = -1, 1, 0
        axis = (0, 0, 1)
        name = 'root'
        if joint is not None:
            name = joint.get('name')
            axis = numbers(joint.find('axis').get('xyz'), (1, 0, 0))
            length = math.sqrt(sum(x*x for x in axis))
            if length < 1e-9:
                raise ValueError('zero joint axis')
            axis = [x/length for x in axis]
            control, scale, offset = arm.get(name, (-1, 1, 0))
            if name in ('revolute_1_3', 'revolute_1_4', 'revolute_1_5', 'revolute_1_7'):
                control = 4
            if name in ('revolute_4', 'revolute_6'):
                control = 5
        groups.append(dict(parent=parent, origin=m, axis=axis, control=control,
                           scale=scale, offset=offset, name=name))
        geometry.append(bytearray())
        return len(groups)-1

    mt = profile['robot']['model']['modelTransformation']
    group(-1, transform(mt['translation'], mt['rotation']))

    def visit(name, g, frame):
        if name in visited:
            raise ValueError('URDF cycle or shared child')
        visited.add(name)
        link_frames[name] = (g, frame)
        for visual in links[name].findall('visual'):
            mesh = visual.find('geometry/mesh')
            if mesh is None:
                raise ValueError('expected owned mesh visual')
            uri = mesh.get('filename')
            if not uri.startswith('package://final2/'):
                raise ValueError('unexpected mesh package')
            path = model / 'final2' / uri.removeprefix('package://final2/')
            sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
            scale = numbers(mesh.get('scale'), (1, 1, 1))
            if max(scale) != min(scale) or min(scale) <= 0:
                raise ValueError('normal conversion requires positive uniform visual scale')
            m = multiply(frame, origin(visual))
            for col in range(3):
                for row in range(3):
                    m[col*4+row] *= scale[col]
            if path not in mesh_cache:
                mesh_cache[path] = list(triangles(path))
            local_points = []
            for p, n, color in mesh_cache[path]:
                p, n = point(m, p), point(m, n, 0)
                local_points.append(p)
                length = math.sqrt(sum(x*x for x in n)) or 1
                geometry[g].extend(struct.pack('<9f', *p, *(x/length for x in n), *color))
            ancestor = g
            while ancestor >= 0 and groups[ancestor]['control'] != 0:
                ancestor = groups[ancestor]['parent']
            if ancestor >= 0:
                low = [min(p[i] for p in local_points) for i in range(3)]
                high = [max(p[i] for p in local_points) for i in range(3)]
                colliders.append(dict(group=g, link=name, centre=[(a+b)/2 for a, b in zip(low, high)],
                                      halfSize=[max((b-a)/2, 0.0001) for a, b in zip(low, high)]))
        for j in children.get(name, []):
            m = multiply(frame, origin(j))
            child = j.find('child').get('link')
            if j.get('type') == 'fixed':
                visit(child, g, m)
            elif j.get('type') == 'continuous':
                visit(child, group(g, m, j), identity())
            else:
                raise ValueError('unsupported joint type')

    visit(next(iter(roots)), 0, identity())
    if visited != set(links):
        raise ValueError('unreachable URDF links')
    tcp_group, tcp_frame = link_frames[profile['tcp']['link']]
    tcp = point(tcp_frame, profile['tcp']['offset'])
    header = bytearray(64)
    struct.pack_into('<8s5q', header, 0, b'PBSIM002', len(groups), sum(len(x)//36 for x in geometry), tcp_group, len(links), 36)
    records, vertices, first = bytearray(), bytearray(), 0
    for g, data in zip(groups, geometry):
        record = bytearray(256)
        count = len(data)//36
        struct.pack_into('<2q16d3d2d2q', record, 0, g['parent'], g['control'], *g['origin'], *g['axis'], g['scale'], g['offset'], first, count)
        records.extend(record)
        vertices.extend(data)
        first += count
    # TCP local coordinates are stored in an extra 256-byte metadata record.
    tail = bytearray(256)
    struct.pack_into('<3d', tail, 0, *tcp)
    arm_frame = profile['frames']['armBase']
    struct.pack_into('<6d', tail, 24, *arm_frame['translation'], *arm_frame['rotation'])
    # Tyre cylinders follow each wheel joint, including the mesh's axial offset.
    wheels = []
    for index, (g, data) in enumerate(zip(groups, geometry)):
        if g['control'] != 4:
            continue
        points = [v[:3] for v in struct.iter_unpack('<9f', data)]
        axial = [sum(p[i]*g['axis'][i] for i in range(3)) for p in points]
        radius = max(math.sqrt(max(0, sum(v*v for v in p)-a*a)) for p, a in zip(points, axial))
        wheels.append(dict(group=index, axialCentre=(min(axial)+max(axial))/2,
                           radius=radius, halfWidth=(max(axial)-min(axial))/2))
    if len(wheels) != 4:
        raise ValueError('expected four wheel meshes')
    struct.pack_into('<8sq', tail, 72, b'PBSWH001', len(wheels))
    for index, wheel in enumerate(wheels):
        struct.pack_into('<q3d', tail, 88+index*32, wheel['group'], wheel['axialCentre'], wheel['radius'], wheel['halfWidth'])
    output.parent.mkdir(parents=True, exist_ok=True)
    collision_offset = len(header)+len(records)+len(tail)+len(vertices)
    struct.pack_into('<2q', header, 48, len(colliders), collision_offset)
    collision_data = b''.join(struct.pack('<q6d', c['group'], *c['centre'], *c['halfSize']) for c in colliders)
    publish(output, header + records + tail + vertices + collision_data)
    receipt = dict(schema='puppybot.sim.assets.v1', links=len(links), visuals=len(robot.findall('link/visual')),
                   groups=len(groups), vertices=first, tcpGroup=tcp_group, wheels=wheels, armColliders=colliders,
                   joints=[{k: v for k, v in g.items() if k in ('name', 'parent', 'control', 'scale', 'offset')} for g in groups],
                   sourceHashes=sources, assetSha256=hashlib.sha256(output.read_bytes()).hexdigest())
    publish(output.with_suffix('.json'), (json.dumps(receipt, indent=2)+'\n').encode())
    print(f'Packed {receipt["visuals"]} visuals, {len(groups)} groups, {first//3:,} triangles into {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'build/flex/sim/puppybot.bin')
    prepare(parser.parse_args().output)
