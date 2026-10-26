// Case data is copied out of the shared JSON arena before vision/API parsing.
import "model.flex";
import "../host/json.flex";

global ps_catalog = 0;
global ps_catalog_size = 0;
global ps_catalog_entries = 0;
global ps_catalog_count = 0;
global ps_catalog_cameras = 0;
global ps_case_index = -1;
global ps_case_objects = 0;
global ps_case_count = 0;
global ps_case_bin = 0;
global ps_case_approach = 0;
global ps_case_settle = 100;
global ps_case_speed = 0;
global ps_case_bin_body = 0;
global ps_case_finger_length = 0;
global ps_case_grasp_offset = 0;
global ps_case_random = 0;
global ps_case_spawn = 0;
global ps_case_camera = 0;
global ps_case_scenery = 0;
global ps_case_scenery_count = 0;
global ps_case_coverage = 0;
global ps_case_coverage_count = 0;

fn ps_case_string(out, text, capacity) {
    let size = pl_size(text); if size >= capacity { return 0; } pb_copy(out, text, size + 1); return 1;
}
fn ps_catalog_load() {
    ps_catalog = alloc(16385); ps_catalog_size = pl_read_file("flex/sim/cases/catalog.json", ps_catalog, 16384); if ps_catalog_size <= 0 { return 0; }
    let root = pj_parse(ps_catalog, ps_catalog_size); let schema = pj_string_field(root, "schema"); let entries = pj_need(root, "cases", 3);
    if pj_error || !pl_equal(schema, "puppybot.cases.v1") || pj_count(entries) < 1 || pj_count(entries) > 16 { return 0; }
    ps_catalog_count = pj_count(entries); ps_catalog_entries = alloc(ps_catalog_count * 768); ps_catalog_cameras = alloc(ps_catalog_count * 8); let i = 0;
    while i < ps_catalog_count {
        let entry = pj_index(entries, i); let id = pj_string_field(entry, "id"); let name = pj_string_field(entry, "name"); let file = pj_string_field(entry, "file");
        let camera = 0; if pj_get(entry, "controller") { let mode = pj_string_field(entry, "controller"); camera = pl_equal(mode, "rgb-search"); if pl_equal(mode, "rgb-house") { camera = 2; } if pl_equal(mode, "rgb-discovery") { camera = 3; } if pl_equal(mode, "rgb-find-return") { camera = 4; } } store64(ps_catalog_cameras + i * 8, camera);
        if pj_error || !pl_size(id) || !ps_case_string(ps_catalog_entries + i * 768, id, 128) || !ps_case_string(ps_catalog_entries + i * 768 + 128, name, 128) || !ps_case_string(ps_catalog_entries + i * 768 + 256, file, 512) { return 0; }
        let j = 0; while j < i { if pl_equal(id, ps_catalog_entries + j * 768) { return 0; } j = j + 1; } i = i + 1;
    }
    return 1;
}
fn ps_case_find(id) {
    let i = 0; while i < ps_catalog_count { if pl_equal(id, ps_catalog_entries + i * 768) { return i; } i = i + 1; } return -1;
}
fn ps_case_file(path) {
    // A generated scene adds one process-local entry; the owned catalog stays intact.
    if ps_catalog_count >= 16 { return -1; }
    let data = alloc(16385); let size = pl_read_file(path, data, 16384);
    if size <= 0 { syscall(11, data, 16385, 0, 0, 0, 0); return -1; }
    let root = pj_parse(data, size); let id = pj_string_field(root, "id"); let mode = pj_string_field(root, "controller");
    if pj_error || !id || !mode { syscall(11, data, 16385, 0, 0, 0, 0); return -1; }
    let camera = -1; if pl_equal(mode, "scene-state") { camera = 0; } if pl_equal(mode, "rgb-search") { camera = 1; } if pl_equal(mode, "rgb-house") { camera = 2; } if pl_equal(mode, "rgb-discovery") { camera = 3; } if pl_equal(mode, "rgb-find-return") { camera = 4; }
    let valid = !pj_error && camera >= 0 && pl_size(id) && ps_case_find(id) < 0;
    let entries = alloc((ps_catalog_count + 1) * 768); let cameras = alloc((ps_catalog_count + 1) * 8); let entry = entries + ps_catalog_count * 768;
    if valid { valid = ps_case_string(entry, id, 128) && ps_case_string(entry + 128, id, 128) && ps_case_string(entry + 256, path, 512); }
    syscall(11, data, 16385, 0, 0, 0, 0);
    if !valid { syscall(11, entries, (ps_catalog_count + 1) * 768, 0, 0, 0, 0); syscall(11, cameras, (ps_catalog_count + 1) * 8, 0, 0, 0, 0); return -1; }
    pb_copy(entries, ps_catalog_entries, ps_catalog_count * 768); pb_copy(cameras, ps_catalog_cameras, ps_catalog_count * 8); store64(cameras + ps_catalog_count * 8, camera);
    syscall(11, ps_catalog_entries, ps_catalog_count * 768, 0, 0, 0, 0); syscall(11, ps_catalog_cameras, ps_catalog_count * 8, 0, 0, 0, 0);
    ps_catalog_entries = entries; ps_catalog_cameras = cameras; ps_catalog_count = ps_catalog_count + 1; return ps_catalog_count - 1;
}
fn ps_case_vector(out, node, name, lo, hi) {
    let values = pj_need(node, name, 3); if pj_error || pj_count(values) != 3 { return 0; } let i = 0;
    while i < 3 {
        let value = pj_real_node(pj_index(values, i)); if pj_error || !f64_is_finite(value) || f64_lt(value, lo) || f64_gt(value, hi) { return 0; }
        pb_vset(out, i, value); i = i + 1;
    }
    return 1;
}
fn ps_case_load(index) {
    if index < 0 || index >= ps_catalog_count { return 0; }
    let data = alloc(16385); let size = pl_read_file(ps_catalog_entries + index * 768 + 256, data, 16384);
    if size <= 0 { syscall(11, data, 16385, 0, 0, 0, 0); return 0; }
    let root = pj_parse(data, size); let schema = pj_string_field(root, "schema"); let id = pj_string_field(root, "id"); let objects = pj_need(root, "objects", 3);
    let count = pj_count(objects); let approach = pj_real(root, "approachX");
    let camera = 0; let controller = pj_get(root, "controller");
    if controller { let name = pj_string_field(root, "controller"); camera = pl_equal(name, "rgb-search"); if pl_equal(name, "rgb-house") { camera = 2; } if pl_equal(name, "rgb-discovery") { camera = 3; } if pl_equal(name, "rgb-find-return") { camera = 4; } if !camera && !pl_equal(name, "scene-state") { syscall(11, data, 16385, 0, 0, 0, 0); return 0; } }
    if camera != load64(ps_catalog_cameras + index * 8) { syscall(11, data, 16385, 0, 0, 0, 0); return 0; }
    if pj_error || !pl_equal(schema, "puppybot.case.v1") || !pl_equal(id, ps_catalog_entries + index * 768) || count < 1 || count > 8 || !f64_is_finite(approach) || f64_lt(approach, 0) || f64_gt(approach, ps_number(3, 10)) { syscall(11, data, 16385, 0, 0, 0, 0); return 0; }
    let records = alloc(8 * 256); pb_zero(records, 8 * 256); let bin = alloc(128); pb_zero(bin, 128); let spawn = alloc(64); pb_zero(spawn, 64); let valid = 1; let i = 0;
    let limit = ps_number(15, 10); if camera >= 2 { limit = f64_from_i64(10); }
    let coverage = alloc(64 * 24); let coverage_count = 0;
    if camera == 2 {
        let route = pj_need(pj_need(root, "navigation", 4), "coverage", 3); coverage_count = pj_count(route); valid = !pj_error && coverage_count >= 2 && coverage_count <= 64;
        while valid && i < coverage_count {
            let point = pj_index(route, i); valid = pj_kind(point) == 3 && pj_count(point) == 3; let k = 0;
            while valid && k < 3 { let value = pj_real_node(pj_index(point, k)); valid = !pj_error && f64_is_finite(value) && f64_le(f64_magnitude(value), limit); store64(coverage + i * 24 + k * 8, value); k = k + 1; } i = i + 1;
        }
    } i = 0;
    // Object record: ID[64], kind, initial position[3], half-size[3], mass,
    // RGB[3], physics body, delivered, yaw, consumed. Real scalars are binary64.
    while i < count && valid {
        let node = pj_index(objects, i); let r = records + i * 256; let name = pj_string_field(node, "id"); let kind = pj_string_field(node, "kind"); let mass = pj_real(node, "mass");
        valid = !pj_error && ps_case_string(r, name, 64) && pl_size(name) && (pl_equal(kind, "ball") || pl_equal(kind, "block")) && f64_is_finite(mass) && f64_gt(mass, 0) && f64_lt(mass, PB_ONE);
        if valid {
            store64(r + 64, pl_equal(kind, "ball")); store64(r + 128, mass);
            valid = ps_case_vector(r + 72, node, "position", pb_neg(limit), limit) && ps_case_vector(r + 96, node, "halfSize", ps_number(5, 1000), ps_number(4, 100)) && ps_case_vector(r + 160, node, "color", 0, f64_from_i64(100));
            if f64_lt(load64(r + 88), load64(r + 112)) { valid = 0; }
            if load64(r + 64) && (load64(r + 96) != load64(r + 104) || load64(r + 96) != load64(r + 112)) { valid = 0; }
            let j = 0; while j < i { if pl_equal(r, records + j * 256) { valid = 0; } j = j + 1; }
            if pj_get(node, "yawDegrees") {
                let yaw = pj_real(node, "yawDegrees"); valid = valid && !pj_error && f64_is_finite(yaw) && f64_le(f64_magnitude(yaw), f64_from_i64(180)); store64(r + 200, pb_radians(yaw));
            }
        }
        i = i + 1;
    }
    // Solid non-target cuboids. Keep these separate from the task objects;
    // their labels/poses are available to the judge, never the RGB detector.
    // Record: ID[48], position[3], half-size[3], RGB[3], physics body.
    let scenery = alloc(8 * 128); pb_zero(scenery, 8 * 128); let props = pj_get(root, "scenery"); let prop_count = 0;
    if props { if pj_kind(props) != 3 { valid = 0; } else { prop_count = pj_count(props); if prop_count > 8 { valid = 0; } } }
    i = 0;
    while i < prop_count && valid {
        let node = pj_index(props, i); let r = scenery + i * 128; let name = pj_string_field(node, "id");
        valid = !pj_error && pl_size(name) && ps_case_string(r, name, 48) && ps_case_vector(r + 48, node, "position", ps_number(-15, 10), ps_number(15, 10)) && ps_case_vector(r + 72, node, "halfSize", ps_number(2, 1000), ps_number(1, 2)) && ps_case_vector(r + 96, node, "color", 0, f64_from_i64(100));
        if f64_lt(load64(r + 64), load64(r + 88)) { valid = 0; }
        let j = 0; while j < i { if pl_equal(r, scenery + j * 128) { valid = 0; } j = j + 1; }
        j = 0; while j < count { if pl_equal(r, records + j * 256) { valid = 0; } j = j + 1; } i = i + 1;
    }
    let gripper = pj_need(root, "gripper", 4); let length = pj_real(gripper, "fingerLength"); let offset = pj_real(gripper, "graspOffset");
    valid = valid && !pj_error && f64_is_finite(length) && f64_is_finite(offset) && f64_ge(length, ps_number(4, 100)) && f64_le(length, ps_number(12, 100)) && f64_ge(offset, f64_mul(length, ps_number(1, 2))) && f64_le(offset, length);
    let container = pj_need(root, "container", 4); let thickness = pj_real(container, "wallThickness"); let success = pj_need(root, "success", 4);
    let settle = pj_integer(success, "settleSteps", 50, 1000); let speed = pj_real(success, "maxLinearSpeed");
    valid = valid && !pj_error && f64_is_finite(thickness) && f64_ge(thickness, ps_number(4, 1000)) && f64_le(thickness, ps_number(2, 100)) && f64_is_finite(speed) && f64_gt(speed, 0) && f64_le(speed, ps_number(5, 100));
    if valid { valid = ps_case_vector(bin, container, "position", pb_neg(limit), limit) && ps_case_vector(bin + 24, container, "innerSize", ps_number(5, 100), ps_number(3, 10)); pb_vset(bin, 6, thickness); }
    let mass = ps_number(3, 10); let fixed = 0;
    if pj_get(container, "mass") { mass = pj_real(container, "mass"); }
    if pj_get(container, "fixed") { fixed = pj_boolean(container, "fixed"); }
    let markers = camera; if pj_get(container, "visionMarkers") { markers = pj_boolean(container, "visionMarkers"); } store64(bin + 80, markers); store64(bin + 88, markers);
    valid = valid && !pj_error && f64_is_finite(mass) && f64_ge(mass, ps_number(1, 100)) && f64_le(mass, f64_from_i64(100));
    store64(bin + 56, mass); store64(bin + 64, fixed);
    if valid && load64(bin + 16) { valid = 0; }
    let random = pj_get(root, "randomFloor");
    if valid && random {
        let low = pj_need(random, "min", 3); let high = pj_need(random, "max", 3); let k = 0;
        valid = !pj_error && pj_count(low) == 2 && pj_count(high) == 2;
        while k < 2 && valid {
            let a = pj_real_node(pj_index(low, k)); let b = pj_real_node(pj_index(high, k));
            valid = !pj_error && f64_is_finite(a) && f64_is_finite(b) && f64_ge(a, ps_number(-15, 10)) && f64_le(b, ps_number(15, 10)) && f64_lt(a, b);
            store64(spawn + k * 8, a); store64(spawn + 16 + k * 8, b); k = k + 1;
        }
        let clearance = pj_real(random, "clearance"); let yaw = pj_real(random, "yawDegrees");
        valid = valid && !pj_error && f64_is_finite(clearance) && f64_ge(clearance, 0) && f64_le(clearance, ps_number(20, 100)) && f64_is_finite(yaw) && f64_ge(yaw, 0) && f64_le(yaw, f64_from_i64(180));
        store64(spawn + 32, clearance); store64(spawn + 40, pb_radians(yaw));
        i = 0; while i < count { if load64(records + i * 256 + 64) { valid = 0; } i = i + 1; }
    }
    if valid && random { valid = ps_layout_generate(records, count, bin, spawn, ps_case_seed); }
    if camera { i = 0; while i < count { if load64(records + i * 256 + 64) { valid = 0; } i = i + 1; } }
    syscall(11, data, 16385, 0, 0, 0, 0);
    if !valid { syscall(11, coverage, 64 * 24, 0, 0, 0, 0); syscall(11, scenery, 8 * 128, 0, 0, 0, 0); syscall(11, spawn, 64, 0, 0, 0, 0); syscall(11, records, 8 * 256, 0, 0, 0, 0); syscall(11, bin, 128, 0, 0, 0, 0); return 0; }
    if ps_case_coverage { syscall(11, ps_case_coverage, 64 * 24, 0, 0, 0, 0); } ps_case_coverage = coverage; ps_case_coverage_count = coverage_count;
    if ps_case_objects { syscall(11, ps_case_objects, 8 * 256, 0, 0, 0, 0); syscall(11, ps_case_bin, 128, 0, 0, 0, 0); }
    if ps_case_spawn { syscall(11, ps_case_spawn, 64, 0, 0, 0, 0); } ps_case_spawn = spawn; ps_case_random = random != 0;
    if ps_case_scenery { syscall(11, ps_case_scenery, 8 * 128, 0, 0, 0, 0); } ps_case_scenery = scenery; ps_case_scenery_count = prop_count;
    ps_case_objects = records; ps_case_count = count; ps_case_bin = bin; ps_case_approach = approach; ps_case_settle = settle; ps_case_speed = speed; ps_case_finger_length = length; ps_case_grasp_offset = offset; ps_case_index = index; ps_case_camera = camera;
    ps_seek_enabled = camera == 4;
    if camera == 3 || camera == 4 { ps_collect_enabled = 1; ps_discovery_enabled = 1; ps_case_camera = 2; } return 1;
}
fn ps_case_body(index) { if !index { return 3; } return index + 7; }

fn ps_finger_length() { if ps_case_index >= 0 { return ps_case_finger_length; } return ps_number(6, 100); }
fn ps_grasp_offset() { if ps_case_index >= 0 { return ps_case_grasp_offset; } return ps_number(45, 1000); }
