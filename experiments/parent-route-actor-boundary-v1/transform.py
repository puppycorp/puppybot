#!/usr/bin/env python3
"""Instrument a private collector copy; never alter active project sources."""


def once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('collector source anchor is absent or ambiguous')
    return text.replace(before, after, 1)


def transform(chase):
    chase = once(chase, 'import "workflow.flex";',
                 'import "workflow.flex";\nimport "actor-attestation.flex";\nimport "parent-boundary.flex";')
    anchor = 'let action=alloc(8);let label=alloc(8);'
    inserted = '''let action=alloc(8);let label=alloc(8);
    // Private research build: record the exact actor input after brick
    // placement and cue selection, and the teacher/map values for this row.
    let parent_boundary=0;let parent_actor=0;
    if mode==3 && base {
        vc_require(vw_fetch && vw_record_map && !vw_sample_actions && !vw_action_noise && !vw_self_keep && !vw_ensemble_count && !vw_straight_bias && !vw_search_cue && !vw_hide_carry && !vw_blackout && !ve_policy_raw,"unsupported parent boundary collection mode");
        parent_actor=pa_open(vc_path(directory,"actor-boundary.bin"),seed,vw_horizon,ve_image_bytes,ve_memory_width);
        parent_boundary=prb_open(vc_path(directory,"map-label-boundary.bin"),seed,vw_horizon);
    }'''
    chase = once(chase, anchor, inserted)
    anchor = '        if ve_contact {vx_contacts=vx_contacts+1;}vx_track(action);ve_step(action);'
    inserted = '''        if parent_actor {
            let frame=vc_json_int(ve_state,"totalSteps",0);
            pa_record(parent_actor,ve_steps,ve_sequence,frame,ve_image,ve_policy_input,ve_policy_output,action);
            prb_record(parent_boundary,ve_steps,ve_sequence,frame,vx_map_base+ve_steps*144,label);
        }
        if ve_contact {vx_contacts=vx_contacts+1;}vx_track(action);ve_step(action);'''
    chase = once(chase, anchor, inserted)
    anchor = '    syscall(3,vx_log,0,0,0,0,0);if vw_record_memory'
    inserted = '    if parent_actor {pa_finish(parent_actor);prb_finish(parent_boundary);}\n    syscall(3,vx_log,0,0,0,0,0);if vw_record_memory'
    return once(chase, anchor, inserted)
