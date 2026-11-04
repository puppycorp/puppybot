import "words.flex";

// Acos: libm 0.2.16 / FreeBSD e_acos.c, Copyright (C) 1993 Sun
// Microsystems, Inc. Permission to use, copy, modify and distribute freely,
// provided this notice is preserved. See ../vendor/f64-math.LICENSE.
fn pb_acos_r(z) {
    let p = f64_mul(z, f64_add(0x3fc5555555555555, f64_mul(z, f64_add(pb_neg(0x3fd4d61203eb6f7d), f64_mul(z, f64_add(0x3fc9c1550e884455, f64_mul(z, f64_add(pb_neg(0x3fa48228b5688f3b), f64_mul(z, f64_add(0x3f49efe07501b288, f64_mul(z, 0x3f023de10dfdf709)))))))))));
    let q = f64_add(0x3ff0000000000000, f64_mul(z, f64_add(pb_neg(0x40033a271c8a2d4b), f64_mul(z, f64_add(0x40002ae59c598ac8, f64_mul(z, f64_add(pb_neg(0x3fe6066c1b8d0159), f64_mul(z, 0x3fb3b8c5b12e9282))))))));
    return f64_div(p, q);
}
fn pb_acos(x) {
    let hx = (x >> 32) & 0xffffffff; let ix = hx & 0x7fffffff;
    let low = 0x3c91a62633145c07;
    if ix >= 0x3ff00000 {
        if ((ix - 0x3ff00000) | (x & 0xffffffff)) == 0 {
            if hx >> 31 { return PB_PI; } return 0;
        }
        return f64_nan();
    }
    if ix < 0x3fe00000 {
        if ix <= 0x3c600000 { return PB_HALF_PI; }
        return f64_sub(PB_HALF_PI, f64_sub(x, f64_sub(low, f64_mul(x, pb_acos_r(f64_mul(x, x))))));
    }
    if hx >> 31 {
        let z = f64_mul(f64_add(0x3ff0000000000000, x), 0x3fe0000000000000); let s = f64_sqrt(z);
        let w = f64_sub(f64_mul(pb_acos_r(z), s), low);
        return f64_mul(0x4000000000000000, f64_sub(PB_HALF_PI, f64_add(s, w)));
    }
    let z = f64_mul(f64_sub(0x3ff0000000000000, x), 0x3fe0000000000000); let s = f64_sqrt(z);
    let df = s & 0xffffffff00000000;
    let c = f64_div(f64_sub(z, f64_mul(df, df)), f64_add(s, df));
    let w = f64_add(f64_mul(pb_acos_r(z), s), c); return f64_mul(0x4000000000000000, f64_add(df, w));
}
fn pb_geometric_yaw(yaw) { return f64_add(yaw, 0x3ff70be937858458); }
fn pb_arm_lateral_offset() { return pb_neg(0x40332669b11ada8f); }
fn pb_tool_pitch(shoulder, elbow, wrist) { return pb_wrap_pi(f64_add(f64_add(f64_sub(shoulder, elbow), wrist), pb_neg(0x40095e2a7b8b5d8d))); }
fn pb_tip_down(shoulder, elbow, pitch) { return pb_wrap_pi(f64_sub(f64_add(f64_sub(pitch, shoulder), elbow), pb_neg(0x40095e2a7b8b5d8d))); }
// Output: yaw, shoulder, elbow, wrist binary64 words, then reachable boolean.
fn pb_ik_branch(out, x, y, z, pitch, radial_sign, elbow_sign) {
    let radius2 = f64_add(f64_mul(x, x), f64_mul(y, y)); let lateral2 = f64_mul(pb_neg(0x40332669b11ada8f), pb_neg(0x40332669b11ada8f));
    let radial = f64_mul(radial_sign, f64_sqrt(pb_fmax(f64_sub(radius2, lateral2), 0x0000000000000000)));
    let yaw = 0;
    if f64_ge(radius2, 0x3d719799812dea11) { yaw = f64_sub(f64_atan2(y, x), f64_atan2(pb_neg(0x40332669b11ada8f), radial)); }
    let rw = f64_sub(f64_sub(radial, 0x3f470699c305e720), f64_mul(0x40430002fe698207, f64_cos(pitch)));
    let zw = f64_sub(f64_sub(z, 0x4034000009695aaa), f64_mul(0x40430002fe698207, f64_sin(pitch)));
    let d2 = f64_add(f64_mul(rw, rw), f64_mul(zw, zw));
    let cosq2 = f64_div(f64_sub(f64_sub(d2, f64_mul(0x4062a00762490460, 0x4062a00762490460)), f64_mul(0x4063600249704d65, 0x4063600249704d65)), f64_mul(f64_mul(0x4000000000000000, 0x4062a00762490460), 0x4063600249704d65));
    let reachable = f64_ge(radius2, lateral2) && f64_ge(cosq2, pb_neg(0x3ff0000000000000)) && f64_le(cosq2, PB_ONE);
    cosq2 = pb_fclamp(cosq2, pb_neg(0x3ff0000000000000), PB_ONE);
    let signed_delta = f64_mul(elbow_sign, pb_acos(cosq2));
    let k1 = f64_add(0x4062a00762490460, f64_mul(0x4063600249704d65, f64_cos(signed_delta)));
    let k2 = f64_mul(0x4063600249704d65, f64_sin(signed_delta));
    let link1 = f64_sub(f64_atan2(zw, rw), f64_atan2(k2, k1));
    let link2 = f64_add(link1, signed_delta);
    let shoulder = f64_sub(link1, 0x3f95aa0c8b49ba8e);
    let elbow = f64_sub(f64_add(shoulder, pb_neg(0x3f8d55b8a5366ddd)), link2);
    pb_vset(out, 0, pb_wrap_pi(f64_sub(yaw, 0x3ff70be937858458)));
    pb_vset(out, 1, shoulder); pb_vset(out, 2, elbow);
    pb_vset(out, 3, pb_tip_down(shoulder, elbow, pitch)); pb_vset(out, 4, reachable);
    return reachable;
}
fn pb_fk(out, yaw, shoulder, elbow, wrist) {
    yaw = pb_geometric_yaw(yaw);
    let p1 = f64_add(shoulder, 0x3f95aa0c8b49ba8e);
    let p2 = f64_add(f64_sub(shoulder, elbow), pb_neg(0x3f8d55b8a5366ddd));
    let p3 = f64_add(f64_add(f64_sub(shoulder, elbow), wrist), pb_neg(0x40095e2a7b8b5d8d));
    let radial = f64_add(f64_add(f64_add(0x3f470699c305e720, f64_mul(0x4062a00762490460, f64_cos(p1))), f64_mul(0x4063600249704d65, f64_cos(p2))), f64_mul(0x40430002fe698207, f64_cos(p3)));
    pb_vset(out, 0, f64_sub(f64_mul(radial, f64_cos(yaw)), f64_mul(pb_neg(0x40332669b11ada8f), f64_sin(yaw))));
    pb_vset(out, 1, f64_add(f64_mul(radial, f64_sin(yaw)), f64_mul(pb_neg(0x40332669b11ada8f), f64_cos(yaw))));
    pb_vset(out, 2, f64_add(f64_add(f64_add(0x4034000009695aaa, f64_mul(0x4062a00762490460, f64_sin(p1))), f64_mul(0x4063600249704d65, f64_sin(p2))), f64_mul(0x40430002fe698207, f64_sin(p3))));
    return 0;
}
fn pb_fk_vector(out, angles) { return pb_fk(out, pb_vget(angles, 0), pb_vget(angles, 1), pb_vget(angles, 2), pb_vget(angles, 3)); }
fn pb_continuity(current, candidate) {
    let yaw = f64_magnitude(pb_wrap_pi(f64_sub(pb_vget(current, 0), pb_vget(candidate, 0))));
    let shoulder = f64_magnitude(pb_wrap_pi(f64_sub(pb_vget(current, 1), pb_vget(candidate, 1))));
    let elbow = f64_magnitude(pb_wrap_pi(f64_sub(pb_vget(current, 2), pb_vget(candidate, 2))));
    let wrist = f64_magnitude(pb_wrap_pi(f64_sub(pb_vget(current, 3), pb_vget(candidate, 3))));
    return f64_add(f64_add(f64_add(yaw, shoulder), f64_mul(0x4000000000000000, elbow)), f64_mul(0x4000000000000000, wrist));
}
fn pb_delta_base(out, angles, frame, dx, dy, dz) {
    let yaw = pb_geometric_yaw(pb_vget(angles, 0));
    let cy = f64_cos(yaw); let sy = f64_sin(yaw);
    if frame == 0 { pb_vset(out, 0, dx); pb_vset(out, 1, dy); pb_vset(out, 2, dz); return 0; }
    if frame == 2 {
        pb_vset(out, 0, f64_sub(f64_mul(dx, cy), f64_mul(dy, sy))); pb_vset(out, 1, f64_add(f64_mul(dx, sy), f64_mul(dy, cy))); pb_vset(out, 2, dz); return 0;
    }
    let pitch = pb_tool_pitch(pb_vget(angles, 1), pb_vget(angles, 2), pb_vget(angles, 3));
    let cp = f64_cos(pitch); let sp = f64_sin(pitch);
    let fx = f64_mul(cp, cy); let fy = f64_mul(cp, sy); let fz = sp;
    let lx = pb_neg(sy); let ly = cy;
    let ux = f64_sub(f64_mul(fy, 0x0000000000000000), f64_mul(fz, ly)); let uy = f64_sub(f64_mul(fz, lx), f64_mul(fx, 0x0000000000000000)); let uz = f64_sub(f64_mul(fx, ly), f64_mul(fy, lx));
    pb_vset(out, 0, f64_add(f64_add(f64_mul(dx, fx), f64_mul(dy, lx)), f64_mul(dz, ux)));
    pb_vset(out, 1, f64_add(f64_add(f64_mul(dx, fy), f64_mul(dy, ly)), f64_mul(dz, uy)));
    pb_vset(out, 2, f64_add(f64_add(f64_mul(dx, fz), f64_mul(dy, 0x0000000000000000)), f64_mul(dz, uz))); return 0;
}

fn pb_ik_tool_down(out, x, y, z) {
    if !pb_ik_branch(out, x, y, z, pb_neg(PB_HALF_PI), PB_ONE, PB_ONE) { return 5; } return 0;
}
fn pb_tooltip_to_wrist(out, x, y, z, pitch) {
    let radial_backoff = f64_mul(0x40430002fe698207, f64_cos(pitch));
    let vertical_backoff = f64_mul(0x40430002fe698207, f64_sin(pitch));
    let radial = f64_sqrt(pb_fmax(f64_sub(f64_add(f64_mul(x, x), f64_mul(y, y)), f64_mul(pb_neg(0x40332669b11ada8f), pb_neg(0x40332669b11ada8f))), 0x0000000000000000));
    let yaw = f64_sub(f64_atan2(y, x), f64_atan2(pb_neg(0x40332669b11ada8f), radial));
    pb_vset(out, 0, f64_sub(x, f64_mul(radial_backoff, f64_cos(yaw))));
    pb_vset(out, 1, f64_sub(y, f64_mul(radial_backoff, f64_sin(yaw))));
    pb_vset(out, 2, f64_sub(f64_sub(z, 0x4034000009695aaa), vertical_backoff)); return 0;
}
fn pb_chain_point(out, radial, z, cy, sy) {
    pb_vset(out, 0, f64_sub(f64_mul(radial, cy), f64_mul(pb_neg(0x40332669b11ada8f), sy)));
    pb_vset(out, 1, f64_add(f64_mul(radial, sy), f64_mul(pb_neg(0x40332669b11ada8f), cy)));
    pb_vset(out, 2, z); return 0;
}
// Five XYZ points in millimetres: yaw, shoulder, elbow, wrist, TCP.
fn pb_arm_chain_points(out, yaw, shoulder, elbow, wrist) {
    yaw = pb_geometric_yaw(yaw); let cy = f64_cos(yaw); let sy = f64_sin(yaw);
    let p1 = f64_add(shoulder, 0x3f95aa0c8b49ba8e);
    let p2 = f64_add(f64_sub(shoulder, elbow), pb_neg(0x3f8d55b8a5366ddd));
    let p3 = f64_add(f64_add(f64_sub(shoulder, elbow), wrist), pb_neg(0x40095e2a7b8b5d8d));
    let shoulder_radial = 0x3f470699c305e720;
    let elbow_radial = f64_add(shoulder_radial, f64_mul(0x4062a00762490460, f64_cos(p1)));
    let elbow_z = f64_add(0x4034000009695aaa, f64_mul(0x4062a00762490460, f64_sin(p1)));
    let wrist_radial = f64_add(elbow_radial, f64_mul(0x4063600249704d65, f64_cos(p2)));
    let wrist_z = f64_add(elbow_z, f64_mul(0x4063600249704d65, f64_sin(p2)));
    let tcp_radial = f64_add(wrist_radial, f64_mul(0x40430002fe698207, f64_cos(p3)));
    let tcp_z = f64_add(wrist_z, f64_mul(0x40430002fe698207, f64_sin(p3)));
    pb_zero(out, 24);
    pb_chain_point(out+24, shoulder_radial, 0x4034000009695aaa, cy, sy);
    pb_chain_point(out+48, elbow_radial, elbow_z, cy, sy);
    pb_chain_point(out+72, wrist_radial, wrist_z, cy, sy);
    pb_chain_point(out+96, tcp_radial, tcp_z, cy, sy); return 0;
}
