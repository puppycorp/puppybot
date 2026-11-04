#!/usr/bin/env python3
"""Add an opt-in visual-stall stop to a disposable contact-stop source copy."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('visual_contact_base', ROOT / 'experiments/contact-stop-v1/transform.py')
contact = importlib.util.module_from_spec(spec); spec.loader.exec_module(contact)

HOOK = r'''// Only saved actor input bytes and checked camera metadata enter this
// heuristic. A repeated frame is suspicion, not proof of actual motion.
fn vx_visual_stop_check(directory,action) {
    let camera=pj_get(ve_state,"camera");let valid=pl_equal(pj_string_field(camera,"pose"),"driving") && pj_boolean(camera,"armSettled");
    let tick=vc_json_int(ve_state,"totalSteps",0);let frame=vc_json_int(pj_get(ve_state,"case"),"perception","frameId");
    let drive=pj_get(pj_get(ve_state,"controller"),"drive");
    let left=vc_json_int(drive,"leftSpeed",0);let right=vc_json_int(drive,"rightSpeed",0);
    if !vs_observe(vx_visual_state,ve_image,ve_image_bytes,valid && frame==tick && !pj_error,tick,left,right) {return 0;}
    vx_visual_reason=vs_reason(vx_visual_state);let trigger=ve_steps;let trigger_image=vc_digest(ve_image,ve_image_bytes);
    pb_zero(action,8);ve_step(action);
    drive=pj_get(pj_get(ve_state,"controller"),"drive");
    vc_require(!vc_json_int(drive,"leftSpeed",0) && !vc_json_int(drive,"rightSpeed",0),"zero command was not echoed");
    let text=alloc(1024);let b=alloc(32);pl_builder(b,text,1024);
    pl_text(b,"{\"schema\":\"puppybot.sim-visual-stall.v1\",\"reason\":");
    if vx_visual_reason==1 {pj_text(b,"repeated_actor_image");}else {pj_text(b,"invalid_observation");}
    pl_text(b,",\"triggerAfterActions\":");pl_int(b,trigger);pl_text(b,",\"observedActions\":");pl_int(b,ve_steps);
    pl_text(b,",\"identicalFrames\":");pl_int(b,load64(vx_visual_state));
    pl_text(b,",\"triggerImageSHA256\":");pj_text(b,trigger_image);
    pl_text(b,",\"triggerTick\":");pl_int(b,tick);pl_text(b,",\"triggerFrameId\":");pl_int(b,frame);
    pl_text(b,",\"triggerLeftSpeed\":");pl_int(b,left);pl_text(b,",\"triggerRightSpeed\":");pl_int(b,right);
    pl_text(b,",\"zeroStopActions\":1,\"zeroCommandEchoObserved\":true,\"stopCommandAcknowledged\":false,\"goalGameCompleted\":false}\n");
    vc_require(!load64(b+24),"visual stall report too large");vc_write(vc_path(directory,"visual-stall-stop.json"),text,load64(b+8));
    syscall(11,trigger_image,65,0,0,0,0);syscall(11,b,32,0,0,0,0);syscall(11,text,1024,0,0,0,0);return 1;
}
'''


def transform(chase, main):
    chase, main = contact.transform(chase, main)
    one = contact.replace_one
    chase = one(chase, 'global vw_contact_stop=0;',
                'global vw_visual_stop=0;global vx_visual_state=0;global vx_visual_image=0;'
                'global vx_visual_reason=0;global vx_visual_stopped_episodes=0;\nglobal vw_contact_stop=0;')
    chase = one(chase, 'fn vx_episode(directory,scene,seed,mode,base,hidden) {',
                HOOK + '\nfn vx_episode(directory,scene,seed,mode,base,hidden) {')
    chase = one(chase, '    while ve_steps<vw_horizon && !vx_contact_stop_reason {\n',
                '    vx_visual_reason=0;if vw_visual_stop {if !vx_visual_state {vx_visual_state=alloc(48);}'
                'if !vx_visual_image {vx_visual_image=alloc(ve_image_bytes);}'
                'vc_require(vs_init(vx_visual_state,vx_visual_image,ve_image_bytes,5),"visual guard init failed");}\n'
                '    while ve_steps<vw_horizon && !vx_contact_stop_reason && !vx_visual_reason {\n')
    chase = one(chase, '        if !vw_contact_stop || !vx_contact_stop_check(directory,action) {\n',
                '        if (!vw_contact_stop || !vx_contact_stop_check(directory,action)) && '
                '(!vw_visual_stop || !vx_visual_stop_check(directory,action)) {\n')
    chase = one(chase, '    // Each row\'s weight becomes its discounted return',
                '    if vw_visual_stop && !vx_visual_reason && ve_steps==vw_horizon {vx_visual_stop_check(directory,action);}\n'
                '    // Each row\'s weight becomes its discounted return')
    anchor = '    if vw_contact_stop {pl_text(b,",\\"contactStopReason\\":");'
    visual = ('    if vw_visual_stop {pl_text(b,",\\"visualStopReason\\":");'
              'if vx_visual_reason==1 {pj_text(b,"repeated_actor_image");}'
              'else if vx_visual_reason==2 {pj_text(b,"invalid_observation");}else {pl_text(b,"null");}'
              'pl_text(b,",\\"countAsFailedGame\\":");pj_bool_text(b,vx_visual_reason!=0);'
              'pl_text(b,",\\"fullHorizonCompleted\\":");pj_bool_text(b,!vx_visual_reason && ve_steps==vw_horizon);}\n')
    chase = one(chase, anchor, visual + anchor)
    chase = one(chase, '    vx_contact_stopped_episodes=0;vc_mkdir(vw_output);',
                '    vx_visual_stopped_episodes=0;vx_contact_stopped_episodes=0;vc_mkdir(vw_output);')
    chase = one(chase, 'if vx_contact_stop_reason {vx_contact_stopped_episodes=vx_contact_stopped_episodes+1;}reaches=reaches+vx_reaches;',
                'if vx_contact_stop_reason {vx_contact_stopped_episodes=vx_contact_stopped_episodes+1;}'
                'if vx_visual_reason {vx_visual_stopped_episodes=vx_visual_stopped_episodes+1;}reaches=reaches+vx_reaches;')
    chase = one(chase, 'pj_bool_text(s,!vx_contact_stopped_episodes);',
                'pj_bool_text(s,!vx_contact_stopped_episodes && !vx_visual_stopped_episodes);'
                'if vw_visual_stop {pl_text(s,",\\"visualStoppedEpisodes\\":");pl_int(s,vx_visual_stopped_episodes);}')
    main = one(main, 'import "contact-stop.flex";', 'import "visual-stall.flex";\nimport "contact-stop.flex";')
    main = one(main, '        else if pl_equal(flag,"--contact-stop") {',
               '        else if pl_equal(flag,"--visual-stall-stop") {vc_require(!vw_visual_stop,"duplicate visual stop");vw_visual_stop=1;}\n'
               '        else if pl_equal(flag,"--contact-stop") {')
    anchor = '    vc_require(!vw_contact_stop || (pl_equal(command,"run")'
    main = one(main, anchor,
               '    vc_require(!vw_visual_stop || (pl_equal(command,"run") && vw_fetch && vw_policy && '
               '!vw_contact_stop && !vw_blackout && !vw_chase_forward && !vw_ensemble_count && !vw_sample_actions && !vw_record_memory),'
               '"visual stop requires an isolated simulated fetch policy run without blackout");\n' + anchor)
    return chase, main
