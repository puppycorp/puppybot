#!/usr/bin/env python3
"""Generate a reproducible room world and six-brick discovery case from a seed."""
import argparse
import collections
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import struct
import sys

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def split_rooms(bounds, count, rng):
    rooms = [list(bounds)]
    while len(rooms) < count:
        candidates = [(index, axis) for index, room in enumerate(rooms) for axis in (0, 1)
                      if room[axis+2]-room[axis] >= 4.05]
        if not candidates:
            raise ValueError('room subdivision exhausted')
        index, axis = max(candidates, key=lambda item: (rooms[item[0]][2]-rooms[item[0]][0])*(rooms[item[0]][3]-rooms[item[0]][1])*rng.uniform(.8, 1.2))
        room = rooms.pop(index)
        cut = round(rng.uniform(room[axis]+2, room[axis+2]-2), 3)
        first, second = room.copy(), room.copy()
        first[axis+2], second[axis] = cut, cut
        rooms.extend((first, second))
    return sorted(rooms)


def adjacency(rooms):
    result = []
    for a, first in enumerate(rooms):
        for b in range(a+1, len(rooms)):
            second = rooms[b]
            for axis in (0, 1):
                other = 1-axis
                fixed = None
                if abs(first[axis+2]-second[axis]) < 1e-8:
                    fixed = first[axis+2]
                elif abs(second[axis+2]-first[axis]) < 1e-8:
                    fixed = first[axis]
                lo, hi = max(first[other], second[other]), min(first[other+2], second[other+2])
                if fixed is not None and hi-lo > 1e-8:
                    result.append(dict(rooms=[a, b], axis=axis, fixed=fixed, low=lo, high=hi))
    return result


def doors_for(edges, count, rng):
    parents = list(range(count))
    def root(index):
        while parents[index] != index:
            index = parents[index]
        return index
    order = [i for i, edge in enumerate(edges) if edge['high']-edge['low'] >= 1.2]
    rng.shuffle(order)
    selected = set()
    for index in order:
        a, b = [root(room) for room in edges[index]['rooms']]
        if a != b:
            parents[a] = b
            selected.add(index)
    if len({root(i) for i in range(count)}) != 1:
        raise ValueError('no connected doorway graph')
    for index in order:
        if index not in selected and rng.random() < .3:
            selected.add(index)
    result = []
    for index, edge in enumerate(edges):
        door = None
        if index in selected:
            width = min(rng.uniform(.8, 1.3), edge['high']-edge['low']-.35)
            centre = rng.uniform(edge['low']+width/2+.15, edge['high']-width/2-.15)
            door = dict(width=width, centre=centre)
        result.append(dict(**edge, door=door))
    return result


def solid(name, centre, size, color, yaw=0, collision=True, cutaway=False):
    return dict(name=name, centre=list(centre), half=[value/2 for value in size],
                yaw=yaw, color=list(color), collision=collision, cutaway=cutaway)


def wall_segment(name, axis, fixed, low, high, bottom=0, top=2.5):
    centre = [fixed, (low+high)/2, (bottom+top)/2]
    size = [.12, high-low, top-bottom]
    if axis:
        centre[:2] = centre[1::-1]
        size[:2] = size[1::-1]
    return solid(name, centre, size, [.76, .74, .68], cutaway=True)


def walls(bounds, edges):
    result = [wall_segment('Wall.west', 0, bounds[0], bounds[1], bounds[3]),
              wall_segment('Wall.east', 0, bounds[2], bounds[1], bounds[3]),
              wall_segment('Wall.south', 1, bounds[1], bounds[0], bounds[2]),
              wall_segment('Wall.north', 1, bounds[3], bounds[0], bounds[2])]
    for index, edge in enumerate(edges):
        name = f'Wall.partition-{index}'
        args = edge['axis'], edge['fixed']
        door = edge['door']
        if door is None:
            result.append(wall_segment(name, *args, edge['low'], edge['high']))
        else:
            lo, hi = door['centre']-door['width']/2, door['centre']+door['width']/2
            result.extend((wall_segment(name+'-a', *args, edge['low'], lo),
                           wall_segment(name+'-b', *args, hi, edge['high']),
                           wall_segment(name+'-lintel', *args, lo, hi, 2.1, 2.5)))
    return result


def distance_to_segment(point, start, end):
    delta = np.asarray(end)-start
    fraction = np.clip(np.dot(np.asarray(point)-start, delta)/max(float(delta@delta), 1e-12), 0, 1)
    return float(np.linalg.norm(np.asarray(point)-(np.asarray(start)+fraction*delta)))


def furniture(rooms, edges, rng):
    result = []
    for index, room in enumerate(rooms):
        centre = [(room[0]+room[2])/2, (room[1]+room[3])/2]
        door_points = []
        for edge in edges:
            if index in edge['rooms'] and edge['door']:
                point = [edge['fixed'], edge['door']['centre']]
                door_points.append(point if not edge['axis'] else point[::-1])
        for attempt in range(100):
            x, y = rng.uniform(room[0]+.65, room[2]-.65), rng.uniform(room[1]+.65, room[3]-.65)
            if math.dist([x, y], centre) < 1.1:
                continue
            if any(distance_to_segment([x, y], centre, door) < .9 for door in door_points):
                continue
            yaw = rng.choice([0, math.pi/2, rng.uniform(-.4, .4)])
            width, depth = rng.uniform(.65, .95), rng.uniform(.4, .6)
            if rng.random() < .5:
                result.append(solid(f'Sofa.{index}', [x, y, .22], [width, depth, .4], [.16, .43, .46], yaw))
            else:
                height = rng.uniform(.42, .8)
                result.append(solid(f'Table.{index}.top', [x, y, height-.025], [width, depth, .05], [.60, .43, .28], yaw))
                c, s = math.cos(yaw), math.sin(yaw)
                for leg, (a, b) in enumerate(((-1, -1), (-1, 1), (1, -1), (1, 1))):
                    dx, dy = a*(width/2-.06), b*(depth/2-.06)
                    result.append(solid(f'Table.{index}.leg-{leg}', [x+c*dx-s*dy, y+s*dx+c*dy, (height-.05)/2], [.06, .06, height-.05], [.24, .26, .27], yaw))
            break
    return result


def free_grid(bounds, objects, resolution=.1):
    xs = np.arange(bounds[0]+resolution/2, bounds[2], resolution)
    ys = np.arange(bounds[1]+resolution/2, bounds[3], resolution)
    x, y = np.meshgrid(xs, ys)
    free = np.ones(x.shape, bool)
    for obj in objects:
        if not obj['collision'] or obj['centre'][2]+obj['half'][2] <= .02 or obj['centre'][2]-obj['half'][2] >= .45:
            continue
        c, s = math.cos(obj['yaw']), math.sin(obj['yaw'])
        dx, dy = x-obj['centre'][0], y-obj['centre'][1]
        a = np.maximum(np.abs(c*dx+s*dy)-obj['half'][0], 0)
        b = np.maximum(np.abs(-s*dx+c*dy)-obj['half'][1], 0)
        free &= a*a+b*b > .2**2
    return free


def flood(free, bounds, spawn, resolution=.1):
    start = (int((spawn[1]-bounds[1])/resolution), int((spawn[0]-bounds[0])/resolution))
    reached = np.zeros_like(free)
    if not (0 <= start[0] < free.shape[0] and 0 <= start[1] < free.shape[1] and free[start]):
        return reached
    queue = collections.deque([start])
    reached[start] = True
    while queue:
        row, col = queue.popleft()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            r, c = row+dr, col+dc
            if 0 <= r < free.shape[0] and 0 <= c < free.shape[1] and free[r, c] and not reached[r, c]:
                reached[r, c] = True
                queue.append((r, c))
    return reached


def generate(seed, count):
    rng = random.Random(seed)
    template = json.loads((ROOT/'flex/sim/cases/discover-house-blocks-into-box.json').read_text())
    for attempt in range(100):
        width, height = round(rng.uniform(7.5, 9), 2), round(rng.uniform(6, 8), 2)
        bounds = [-width/2, -height/2, width/2, height/2]
        try:
            rooms = split_rooms(bounds, count, rng)
            edges = doors_for(adjacency(rooms), count, rng)
        except ValueError:
            continue
        start_room = rng.randrange(count)
        room = rooms[start_room]
        spawn = [(room[0]+room[2])/2, (room[1]+room[3])/2, rng.uniform(-math.pi, math.pi)]
        c, s = math.cos(spawn[2]), math.sin(spawn[2])
        corners = np.array([[x-spawn[0], y-spawn[1]] for x in (bounds[0], bounds[2]) for y in (bounds[1], bounds[3])])
        if np.abs(corners@np.array([[c, -s], [s, c]])).max() > 9.6:
            continue
        objects = walls(bounds, edges)+furniture(rooms, edges, rng)
        free = free_grid(bounds, objects)
        reached = flood(free, bounds, spawn)
        if not all(reached[int(((r[1]+r[3])/2-bounds[1])/.1), int(((r[0]+r[2])/2-bounds[0])/.1)] for r in rooms):
            continue
        case = copy.deepcopy(template)
        case['id'] = f'generated-house-{seed}'
        case['container']['position'] = [spawn[0]+c*.34+s*.24, spawn[1]+s*.34-c*.24, 0]
        placed = [spawn[:2], case['container']['position'][:2]]
        order = list(range(count))
        rng.shuffle(order)
        valid = True
        for index, item in enumerate(case['objects']):
            target_room = rooms[order[index % count]]
            for trial in range(1000):
                point = [rng.uniform(target_room[0]+.5, target_room[2]-.5), rng.uniform(target_room[1]+.5, target_room[3]-.5)]
                row, col = int((point[1]-bounds[1])/.1), int((point[0]-bounds[0])/.1)
                if reached[row, col] and all(math.dist(point, prior) > .5 for prior in placed):
                    item['position'][:2] = point
                    item['yawDegrees'] = rng.uniform(-180, 180)
                    placed.append(point)
                    break
            else:
                valid = False
                break
        if valid:
            floors = [solid(f'Floor.{i}', [(r[0]+r[2])/2, (r[1]+r[3])/2, -.016], [r[2]-r[0], r[3]-r[1], .032], [.58+rng.uniform(-.04, .04), .43, .29], collision=False) for i, r in enumerate(rooms)]
            return dict(schema='puppybot.generated-layout.v1', seed=seed, rooms=rooms, edges=edges,
                        bounds=bounds, spawn=spawn, startRoom=start_room,
                        objects=floors+objects, case=case,
                        validation=dict(connectedDoorGraph=True, allRoomCentresReachableWith20cmRadius=True,
                                        sixReachableBrickLocations=True, generationAttempt=attempt+1,
                                        scope='Geometry/connectivity preflight; does not guarantee Ackermann parking or successful pickup'))
    raise ValueError('could not generate a connected layout within the bounded attempts')


def mesh_box(obj):
    vertices = []
    c, s = math.cos(obj['yaw']), math.sin(obj['yaw'])
    for index in range(8):
        x, y, z = [obj['half'][axis]*(1 if index & (1 << axis) else -1) for axis in range(3)]
        vertices.append([obj['centre'][0]+c*x-s*y, obj['centre'][1]+s*x+c*y, obj['centre'][2]+z])
    faces = [([0, 4, 6, 2], [-1, 0, 0]), ([1, 3, 7, 5], [1, 0, 0]),
             ([0, 1, 5, 4], [0, -1, 0]), ([2, 6, 7, 3], [0, 1, 0]),
             ([0, 2, 3, 1], [0, 0, -1]), ([4, 5, 7, 6], [0, 0, 1])]
    full, overview = bytearray(), bytearray()
    for face, normal in faces:
        normal = [c*normal[0]-s*normal[1], s*normal[0]+c*normal[1], normal[2]]
        for index in (face[0], face[1], face[2], face[0], face[2], face[3]):
            point = vertices[index]
            full.extend(struct.pack('<9f', *point, *normal, *obj['color']))
            cut = point.copy()
            if obj['cutaway']:
                cut[2] = min(cut[2], .38)
            overview.extend(struct.pack('<9f', *cut, *normal, *obj['color']))
    return full, overview


def environment_bytes(layout):
    colliders = [obj for obj in layout['objects'] if obj['collision']]
    assert 1 <= len(colliders) <= 160
    records, full, overview = bytearray(), bytearray(), bytearray()
    for obj in colliders:
        record = bytearray(128)
        name = obj['name'].encode('ascii')
        assert len(name) < 48
        record[:len(name)] = name
        struct.pack_into('<7d', record, 48, *obj['centre'], *obj['half'], obj['yaw'])
        records.extend(record)
    for obj in layout['objects']:
        a, b = mesh_box(obj)
        full.extend(a)
        overview.extend(b)
    header = bytearray(256)
    struct.pack_into('<8s3Q', header, 0, b'PBENV001', len(colliders), len(full)//36, len(overview)//36)
    struct.pack_into('<4d3d', header, 64, *layout['bounds'], *layout['spawn'])
    title = f"Generated {len(layout['rooms'])}-room layout seed {layout['seed']}".encode('ascii')
    header[128:128+len(title)] = title
    return header+records+full+overview


def preview(layout, output):
    os.environ.setdefault('MPLCONFIGDIR', '/tmp/puppybot-map-matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    fig, axis = plt.subplots(figsize=(8, 7), constrained_layout=True)
    for index, room in enumerate(layout['rooms']):
        axis.add_patch(Rectangle(room[:2], room[2]-room[0], room[3]-room[1], facecolor=['#f1eee5', '#e4e9e8'][index % 2]))
        axis.text((room[0]+room[2])/2, (room[1]+room[3])/2+.65, f'Room {index+1}', ha='center', color='#666666')
    for obj in layout['objects']:
        if not obj['collision'] or obj['centre'][2]-obj['half'][2] >= .45:
            continue
        x, y = obj['centre'][:2]
        hx, hy = obj['half'][:2]
        axis.add_patch(Rectangle((x-hx, y-hy), hx*2, hy*2, angle=math.degrees(obj['yaw']), rotation_point='center', facecolor='#26363d' if obj['name'].startswith('Wall.') else '#617c79'))
    for item in layout['case']['objects']:
        axis.scatter(*item['position'][:2], c=[np.array(item['color'])/100], edgecolors='black', s=45, zorder=5)
    spawn = layout['spawn']
    axis.arrow(spawn[0], spawn[1], .35*math.cos(spawn[2]), .35*math.sin(spawn[2]), width=.035, color='#007da8', zorder=6)
    axis.scatter(*layout['case']['container']['position'][:2], marker='s', s=100, facecolors='none', edgecolors='#007da8', linewidth=2)
    bounds = layout['bounds']
    axis.set(xlim=(bounds[0]-.3, bounds[2]+.3), ylim=(bounds[1]-.3, bounds[3]+.3),
             xlabel='World x (m)', ylabel='World y (m)', aspect='equal',
             title=f"Seed {layout['seed']} | {len(layout['rooms'])} rooms | six bricks\nReference scene only - no floorplan supplied to the robot")
    fig.savefig(output/'floorplan.png', dpi=150)
    plt.close(fig)


def write(layout, output):
    output.mkdir(parents=True, exist_ok=False)
    (output/'environment.bin').write_bytes(environment_bytes(layout))
    (output/'case.json').write_text(json.dumps(layout['case'], indent=2)+'\n')
    (output/'layout.json').write_text(json.dumps(layout, indent=2)+'\n')
    preview(layout, output)
    manifest = {name: hashlib.sha256((output/name).read_bytes()).hexdigest() for name in ('environment.bin', 'case.json', 'layout.json')}
    (output/'manifest.json').write_text(json.dumps(dict(seed=layout['seed'], hashes=manifest), indent=2)+'\n')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--rooms', type=int, choices=range(2, 7), default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.seed <= 4294967295:
        parser.error('--seed must be between 0 and 4294967295')
    output = write(generate(args.seed, args.rooms), args.output.resolve())
    print(f'Generated {output}\nflexscript run sim.flex --case-file "{output / "case.json"}" --environment "{output / "environment.bin"}"')


if __name__ == '__main__':
    main()
