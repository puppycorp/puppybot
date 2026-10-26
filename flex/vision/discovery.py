#!/usr/bin/env python3
"""Active wrist-stereo mapping from RGB and estimated robot/camera geometry.

No simulator imports, depth buffer, environment bounds, colliders or object IDs.
The fixed 20 m grid is storage capacity in the robot's arbitrary startup frame.
"""
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

CELLS = 200
RESOLUTION = .1
ORIGIN = -10.


def camera(frame):
    values = np.asarray(frame['calibration'], dtype=np.float64).reshape(4, 3)
    rotation = np.column_stack((values[2], values[3], values[1]))
    if not np.isfinite(values).all() or np.linalg.norm(rotation.T @ rotation-np.eye(3)) > .01:
        raise ValueError('invalid estimated camera calibration')
    return values[0], rotation


def robot_mask(frame, size):
    """Project only encoder-derived robot boxes, independent of surface colour."""
    eye, rotation = camera(frame)
    yy, xx = np.indices(size[::-1])
    rays = np.stack(((xx-size[0]/2)/(415.6921938*size[0]/640),
        (yy-size[1]/2)/(415.6921938*size[1]/480), np.ones_like(xx)), axis=2) @ rotation.T
    mask = np.zeros(size[::-1], bool)
    for values in frame['robot']:
        values = np.asarray(values, np.float64)
        if values.shape != (15,) or not np.isfinite(values).all() or (values[12:] <= 0).any():
            raise ValueError('invalid encoder-derived robot box')
        axes = values[3:12].reshape(3,3).T
        if np.linalg.norm(axes.T @ axes-np.eye(3)) > .01:
            raise ValueError('invalid robot box rotation')
        origin = (eye-values[:3]) @ axes
        direction = rays @ axes
        parallel = np.abs(direction) < 1e-9
        extent = values[12:]+.003
        divisor = np.where(parallel, 1., direction)
        first, second = (-extent-origin)/divisor, (extent-origin)/divisor
        low = np.where(parallel, -np.inf, np.minimum(first,second)).max(axis=2)
        high = np.where(parallel, np.inf, np.maximum(first,second)).min(axis=2)
        mask |= (low <= high) & (high > .005) & ~(parallel & (np.abs(origin)>extent)).any(axis=2)
    return cv2.dilate(mask.astype(np.uint8), np.ones((5,5),np.uint8)).astype(bool)


def cloud(frames):
    """Rectify two translated wrist views and triangulate consistent matches."""
    images = [np.fromfile(f['rgb'], np.uint8).reshape(480, 640, 3) for f in frames]
    eyes, rotations = zip(*(camera(f) for f in frames))
    baseline = float(np.linalg.norm(eyes[0]-eyes[1]))
    if not .025 <= baseline <= .15:
        raise ValueError('wrist stereo needs a measured 2.5-15 cm translation')
    size = (320, 240)
    intrinsic = np.array([[207.8460969, 0, 160], [0, 207.8460969, 120], [0, 0, 1.]])
    relative_rotation = rotations[1].T @ rotations[0]
    translation = rotations[1].T @ (eyes[0]-eyes[1])
    first, second, p1, p2, q, _, _ = cv2.stereoRectify(
        intrinsic, None, intrinsic, None, size, relative_rotation, translation.reshape(3, 1),
        flags=cv2.CALIB_ZERO_DISPARITY, alpha=1)
    vertical = abs(p2[1, 3]) > abs(p2[0, 3])
    # Compact radial wrist translations rectify vertically; lateral ones
    # rectify horizontally. Keep disparity positive on the selected axis.
    axis = int(vertical)
    shift = p2[axis,3]/p2[axis,axis]
    if shift > 0:
        return cloud(frames[::-1])
    if vertical or p1[0,0] < 0:
        # Forward wrist motion rotates the rectified optical axis strongly.
        # Keep the actual viewing direction centred, rather than accepting an
        # alpha-scaled canvas whose principal point can lie far outside it.
        direction = (first[:,2]+second[:,2])/2
        focal = intrinsic[0,0]
        cx = size[0]/2-focal*direction[0]/direction[2]
        cy = size[1]/2-focal*direction[1]/direction[2]
        p1 = np.array([[focal,0,cx,0],[0,focal,cy,0],[0,0,1,0.]])
        p2 = p1.copy();p2[axis,3] = focal*shift
        q = np.array([[1,0,0,-cx],[0,1,0,-cy],[0,0,0,focal],[0,0,-1/shift,0.]])
    rectified = []
    self_masks = []
    valid_masks = []
    for frame, image, rotation, projection in zip(frames, images, (first, second), (p1, p2)):
        maps = cv2.initUndistortRectifyMap(intrinsic, None, rotation, projection, size, cv2.CV_32FC1)
        gray = cv2.cvtColor(cv2.resize(image, size), cv2.COLOR_RGB2GRAY)
        rectified.append(cv2.remap(gray, *maps, cv2.INTER_LINEAR))
        # Preserve the common field of view when the wrist views toe in.
        # Rectification adds borders; a complete matching patch must still
        # come from real sensor pixels in both images.
        valid_mask = cv2.remap(np.ones(gray.shape, np.uint8), *maps, cv2.INTER_NEAREST)
        valid_masks.append(cv2.erode(valid_mask, np.ones((5,5),np.uint8),
            borderType=cv2.BORDER_CONSTANT, borderValue=0).astype(bool))
        # Moving links violate stereo's static-scene assumption. Their known
        # geometry supplies the mask; teal furniture must remain observable.
        if 'robot' in frame:
            self_mask = robot_mask(frame, size)
        else:
            # Retain conservative behaviour for old recordings without FK.
            rgb = cv2.resize(image, size).astype(np.int32)
            self_mask = (rgb[:,:,1] > rgb[:,:,0]*1.3) & (rgb[:,:,2] > rgb[:,:,0]*1.3) & (rgb[:,:,2] > rgb[:,:,1]*.7)
            self_mask = cv2.dilate(self_mask.astype(np.uint8), np.ones((5,5),np.uint8))
        self_masks.append(cv2.remap(self_mask.astype(np.uint8), *maps, cv2.INTER_NEAREST).astype(bool))
    def matcher(minimum):
        return cv2.StereoSGBM_create(minDisparity=minimum, numDisparities=96, blockSize=5,
            P1=8*25, P2=32*25, disp12MaxDiff=1, uniquenessRatio=12,
            speckleWindowSize=40, speckleRange=1, mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
    matching = [im.T.copy() if vertical else im for im in rectified]
    left = matcher(0).compute(*matching).astype(np.float32)/16
    right = matcher(-96).compute(*matching[::-1]).astype(np.float32)/16
    if vertical:
        left, right = left.T, right.T
    yy, xx = np.indices(left.shape)
    rx = xx if vertical else np.rint(xx-left).astype(int)
    ry = np.rint(yy-left).astype(int) if vertical else yy
    valid = (left > 2) & (rx >= 0) & (rx < size[0]) & (ry >= 0) & (ry < size[1])
    matched = (np.clip(ry,0,size[1]-1),np.clip(rx,0,size[0]-1))
    valid &= np.abs(left+right[matched]) < .75
    valid &= valid_masks[0] & valid_masks[1][matched]
    valid &= ~self_masks[0] & ~self_masks[1][matched]
    points = cv2.reprojectImageTo3D(left, q)
    with np.errstate(invalid='ignore'):
        points = points @ first @ rotations[0].T + eyes[0]
    valid &= np.isfinite(points).all(axis=2)
    # Repeated floor lines can produce a self-consistent wrong disparity.
    # Independently verify textured ground patches against their calibrated
    # plane homography. Untextured/occluded regions remain unknown.
    rays = np.stack(((xx-p1[0,2])/p1[0,0], (yy-p1[1,2])/p1[1,1], np.ones_like(xx)), axis=2)
    rays = rays @ first @ rotations[0].T
    downward = rays[:,:,2] < -.05
    scale = -eyes[0][2]/np.where(downward, rays[:,:,2], -1)
    ground = eyes[0]+rays*scale[:,:,None]
    projected = (ground-eyes[1]) @ rotations[1] @ second.T
    depth = np.maximum(projected[:,:,2], .001)
    u = (p2[0,0]*projected[:,:,0]/depth+p2[0,2]).astype(np.float32)
    v = (p2[1,1]*projected[:,:,1]/depth+p2[1,2]).astype(np.float32)
    inside = downward & (projected[:,:,2]>.01) & (u>3) & (u<317) & (v>3) & (v<237)
    warped = cv2.remap(rectified[1], u, v, cv2.INTER_LINEAR).astype(np.float32)
    photo_error = cv2.boxFilter(np.abs(rectified[0].astype(np.float32)-warped), -1, (5,5))
    other_self = cv2.remap(self_masks[1].astype(np.uint8),u,v,cv2.INTER_NEAREST).astype(bool)
    other_valid = cv2.remap(valid_masks[1].astype(np.uint8),u,v,cv2.INTER_NEAREST).astype(bool)
    ground_match = inside & valid_masks[0] & other_valid & (photo_error < 10) & ~self_masks[0] & ~other_self
    gray = rectified[0].astype(np.float32)
    mean = cv2.boxFilter(gray, -1, (5,5))
    textured = (cv2.boxFilter(gray*gray, -1, (5,5))-mean*mean > 3) | (cv2.cornerMinEigenVal(rectified[0], 3) > .0001)
    # A repeating wall/floor pattern can also agree with the ground-plane
    # homography. Require independent metric stereo support near that plane.
    floor = ground_match & textured & valid & (np.abs(points[:,:,2]) < .025)
    obstacles = valid & ~ground_match & (points[:,:,2]>.035)
    return np.vstack((ground[floor], points[obstacles])), dict(baselineM=baseline,
        consistentPixels=int(valid.sum()), verifiedFloorPixels=int(floor.sum()))


def cell(xy):
    return np.floor((np.asarray(xy)-ORIGIN)/RESOLUTION).astype(int)


def position(ij):
    return (np.asarray(ij)+.5)*RESOLUTION+ORIGIN


def update(free, occupied, points, pose, detail, height_seen, height_confirmed, floor_detail=None):
    delta = points[:, :2]-np.asarray(pose[:2])
    distance = np.linalg.norm(delta, axis=1)
    valid = (distance > .12) & (distance < 1.3)
    points = points[valid]
    indices = cell(points[:, :2])
    valid = (indices >= 0).all(axis=1) & (indices < CELLS).all(axis=1)
    points, indices = points[valid], indices[valid]
    floor = np.abs(points[:, 2]) < .012
    obstacles = (points[:, 2] > .02) & (points[:, 2] < .45) & (np.linalg.norm(points[:, :2]-pose[:2], axis=1) > .24)
    counts = np.zeros_like(free)
    np.add.at(counts, (indices[floor, 1], indices[floor, 0]), 1)
    free[:] = np.minimum(30000, free+np.minimum(counts, 20))
    # Floor beside a leg must not erase that leg. Track contradictory height
    # evidence in 2 cm subcells and height bins, retaining any confirmed voxel in each
    # 10 cm navigation cell. An unseen obstacle keeps its previous score.
    fine = np.floor((points[:,:2]-ORIGIN)/(RESOLUTION/5)).astype(int)
    fine = np.clip(fine,0,CELLS*5-1)
    hits = np.zeros(detail.shape,np.int32); misses = np.zeros_like(hits)
    np.add.at(hits,(fine[obstacles,1],fine[obstacles,0]),1)
    np.add.at(misses,(fine[floor,1],fine[floor,0]),1)
    if floor_detail is not None:
        floor_detail[:] = np.minimum(30000, floor_detail+np.minimum(misses,20))
    hit = hits>=4
    # Confirm the same 3D region, not merely the same floor column. Repeated
    # floor textures can otherwise vote for incompatible obstacle heights.
    height = np.floor(points[obstacles,2]/.02).astype(int)
    voxel = (fine[obstacles,1]*(CELLS*5)+fine[obstacles,0])*32+height
    voxels,counts = np.unique(voxel,return_counts=True); voxels = voxels[counts>=4]
    height_hit = np.zeros(detail.shape,np.uint32)
    np.bitwise_or.at(height_hit.ravel(),voxels//32,np.left_shift(np.uint32(1),(voxels%32).astype(np.uint32)))
    height_confirmed |= height_seen & height_hit
    height_seen |= height_hit
    detail[:] = np.clip(detail+hit-((misses>=4)&~hit),0,20)
    height_seen[detail==0] = 0; height_confirmed[detail==0] = 0
    # The known 28x22 cm chassis footprint is the only non-image free-space
    # seed. Rasterization is local to the current pose, never a room layout.
    c,s = math.cos(pose[2]),math.sin(pose[2])
    rotation = np.array([[c,-s],[s,c]])
    corners = np.array([[-.14,-.11],[.14,-.11],[.14,.11],[-.14,.11]]) @ rotation.T+pose[:2]
    footprint = np.zeros_like(free, np.uint8)
    cv2.fillConvexPoly(footprint,cell(corners).astype(np.int32),1)
    footprint = footprint.astype(bool)
    free[footprint] = np.maximum(free[footprint], 100)
    # The rover currently occupies this footprint. Old ambiguous stereo
    # votes cannot simultaneously make it an obstacle in its own local map.
    body = np.repeat(np.repeat(footprint,5,axis=0),5,axis=1)
    detail[body] = 0; height_seen[body] = 0; height_confirmed[body] = 0
    occupied[:] = np.where(height_confirmed!=0,detail,0).reshape(CELLS,5,CELLS,5).max(axis=(1,3))
    if floor_detail is not None:
        # Only the actual chassis footprint seeds fine floor. Coarse free
        # cells do not fill unseen subcells beside a box or furniture leg.
        fine_footprint = np.zeros(detail.shape,np.uint8)
        cv2.fillConvexPoly(fine_footprint,np.floor((corners-ORIGIN)/(RESOLUTION/5)).astype(np.int32),1)
        floor_detail[fine_footprint.astype(bool)] = np.maximum(floor_detail[fine_footprint.astype(bool)],100)
    return dict(floorPoints=int(floor.sum()), obstaclePoints=int(obstacles.sum()))


def navigation(free, occupied, pose, visits):
    # Height outliers must agree in two stereo observations. A verified floor
    # patch contradicts height evidence only in the same 2 cm subcell.
    known_free = (free >= 3) & (occupied < 2)
    blocked = occupied >= 2
    # Unknown and occupied space both exclude the complete robot footprint.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    # This grid proposes frontiers. Native Hybrid A* additionally checks the
    # complete oriented chassis rectangle against observed.bin at every sample.
    safe = cv2.erode(known_free.astype(np.uint8), np.ones((3,3),np.uint8)).astype(bool)
    safe &= ~cv2.dilate(blocked.astype(np.uint8), kernel).astype(bool)
    x, y = cell(pose[:2])
    # The current centre can straddle a cell boundary; never seed remote free cells.
    start = (int(y), int(x))
    distance = {start: 0.}
    queue = [start]
    for row, col in queue:
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = row+dr, col+dc
            if 0 <= nr < CELLS and 0 <= nc < CELLS and safe[nr, nc] and (nr, nc) not in distance:
                distance[nr, nc] = distance[(row, col)]+RESOLUTION
                queue.append((nr, nc))
    unknown = (~known_free & ~blocked).astype(np.float32)
    gain = cv2.boxFilter(unknown, -1, (9, 9), normalize=False)
    comfortable = cv2.erode(known_free.astype(np.uint8), np.ones((5,5),np.uint8)).astype(bool)
    candidates = []
    for (row, col), travelled in distance.items():
        if travelled < .25 or gain[row, col] < 8:
            continue
        xy = position([col, row])
        # Old scan locations must not become novel again on a long mission.
        penalty = sum(math.exp(-np.sum((xy-v[:2])**2)/.12) for v in visits)
        score = gain[row, col]/(1+travelled)-20*penalty
        # Face the local frontier, with heading alternatives for Ackermann reachability.
        ry, cx = np.nonzero(unknown[max(0,row-4):row+5, max(0,col-4):col+5])
        heading = math.atan2(float(ry.mean()-min(4,row)), float(cx.mean()-min(4,col))) if len(ry) else pose[2]
        candidates.append((score, [float(xy[0]), float(xy[1]), heading], bool(comfortable[row,col]) and score>0))
    candidates.sort(key=lambda item: -item[0])
    goals = []
    # Prefer room to steer and localize at a frontier. Keep two proposals
    # for narrower observed passages, and preserve the original fallback
    # when no comfortable frontier exists. Traversability is unchanged.
    for preferred, limit in ((True,6),(False,8),(None,8)):
        for _, candidate, comfort in candidates:
            if preferred is not None and comfort != preferred:
                continue
            if len(goals)>=limit:
                break
            if all(math.dist(candidate[:2], g[:2]) > .24 for g in goals):
                goals.append(candidate)
    return safe, known_free, blocked, goals


def run(request, directory):
    if len(request['frames']) != 2 or not np.isfinite(request['pose']).all() or len(request['pose']) != 3:
        raise ValueError('mapping requires two RGB frames and one finite local pose')
    directory.mkdir(parents=True, exist_ok=True)
    state = directory/'evidence.npz'
    if state.exists():
        with np.load(state) as previous:
            free, occupied, visits = previous['free'], previous['occupied'], previous['visits'].tolist()
            detail = previous['detail'] if 'detail' in previous.files else np.repeat(np.repeat(np.minimum(occupied,20),5,axis=0),5,axis=1).astype(np.int16)
            height_seen = previous['heightSeen'] if 'heightSeen' in previous.files else np.zeros(detail.shape,np.uint32)
            # Old confirmed columns have no stored height. Retain them until
            # directly contradicted rather than inventing missing geometry.
            height_confirmed = previous['heightConfirmed'] if 'heightConfirmed' in previous.files else np.where(detail>=2,np.uint32(0xffffffff),np.uint32(0))
            floor_detail = previous['floorDetail'] if 'floorDetail' in previous.files else np.zeros(detail.shape,np.int32)
    else:
        free = np.zeros((CELLS, CELLS), np.int32)
        occupied = np.zeros_like(free)
        detail = np.zeros((CELLS*5,CELLS*5),np.int16)
        height_seen = np.zeros(detail.shape,np.uint32); height_confirmed = np.zeros_like(height_seen)
        floor_detail = np.zeros(detail.shape,np.int32)
        visits = []
    points, metrics = cloud(request['frames'])
    metrics.update(update(free, occupied, points, request['pose'], detail, height_seen, height_confirmed, floor_detail))
    if request.get('newScan'):
        visits.append(request['pose'])
    safe, known_free, blocked, goals = navigation(free, occupied, request['pose'], visits)
    np.savez_compressed(state, free=free, occupied=occupied, detail=detail, heightSeen=height_seen, heightConfirmed=height_confirmed, floorDetail=floor_detail, visits=np.asarray(visits).reshape(-1,3))
    safe_bytes = (~safe).astype(np.uint8).tobytes()
    (directory/'safe.bin').write_bytes(safe_bytes)
    (directory/'observed.bin').write_bytes((~known_free).astype(np.uint8).tobytes())
    detail_bytes = ((floor_detail<3) | ((height_confirmed!=0)&(detail>=2))).astype(np.uint8).tobytes()
    (directory/'observed-detail.bin').write_bytes(detail_bytes)
    (directory/f'observed-detail-{request["frameId"]}.bin').write_bytes(detail_bytes)
    (directory/f'observed-{request["frameId"]}.bin').write_bytes((~known_free).astype(np.uint8).tobytes())
    (directory/f'safe-{request["frameId"]}.bin').write_bytes(safe_bytes)
    (directory/f'input-{request["frameId"]}.json').write_text(json.dumps(request, indent=2)+'\n')
    map_image = np.full((CELLS, CELLS, 3), (65, 65, 65), np.uint8)
    map_image[known_free] = (230, 230, 230)
    map_image[blocked] = (35, 35, 180)
    map_image[safe] = (190, 235, 190)
    for point in visits:
        x, y = cell(point[:2]);cv2.circle(map_image, (int(x),int(y)), 1, (240,140,20), -1)
    for goal in goals:
        x, y = cell(goal[:2]);cv2.circle(map_image, (int(x),int(y)), 1, (20,220,250), -1)
    rows, cols = np.nonzero(known_free | blocked)
    if len(rows):
        lo = max(0, min(int(rows.min()), int(cols.min()))-4)
        hi = min(CELLS, max(int(rows.max()), int(cols.max()))+5)
        map_image = map_image[lo:hi, lo:hi]
    cv2.imwrite(str(directory/'map.png'), cv2.resize(map_image[::-1], (800,800), interpolation=cv2.INTER_NEAREST))
    result = dict(schema='puppybot.discovery.v1', source='tcp-rgb-active-stereo',
        frameId=request['frameId'], cells=CELLS, resolutionM=RESOLUTION, originM=[ORIGIN,ORIGIN],
        freeCells=int(known_free.sum()), occupiedCells=int(blocked.sum()), safeCells=int(safe.sum()),
        knownAreaM2=float((known_free|blocked).sum()*RESOLUTION**2), scans=len(visits), goals=goals, **metrics)
    (directory/'map.json').write_text(json.dumps(result, indent=2)+'\n')
    (directory/f'observation-{request["frameId"]}.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(json.loads(args.request.read_text()), args.output)
    print(json.dumps(result))


if __name__ == '__main__':
    cv2.setNumThreads(1)
    main()
