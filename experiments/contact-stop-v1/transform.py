#!/usr/bin/env python3
"""Add an opt-in simulator-only contact stop to a disposable source copy."""


GLOBALS = '''global vw_contact_stop=0;
global vx_contact_guard=0;
global vx_contact_stop_reason=0;
global vx_contact_stopped_episodes=0;
'''

HOOKS = r'''// The contact cue is simulator feedback, not a physical sensor. A zero
// command echo is not a braking or physical-stop acknowledgement.
fn vx_contact_stop_report(directory,reason,echoed) {
    let text=alloc(1024);let b=alloc(32);pl_builder(b,text,1024);
    pl_text(b,"{\"schema\":\"puppybot.sim-contact-stop.v1\",\"reason\":");
    if reason==1 {pj_text(b,"sustained_contact");}else {pj_text(b,"invalid_observation");}
    pl_text(b,",\"observedActions\":");pl_int(b,ve_steps);
    pl_text(b,",\"triggerAfterActions\":");pl_int(b,ve_steps-1);
    pl_text(b,",\"zeroStopActions\":1");
    pl_text(b,",\"consecutiveContactSamples\":");pl_int(b,load64(vx_contact_guard));
    pl_text(b,",\"zeroCommandEchoObserved\":");pj_bool_text(b,echoed);
    pl_text(b,",\"stopCommandAcknowledged\":false,\"goalGameCompleted\":false,\"scope\":\"simulator only; physical stop unverified\"}\n");
    vc_require(!load64(b+24),"contact stop report too large");vc_write(vc_path(directory,"contact-stop.json"),text,load64(b+8));
    syscall(11,b,32,0,0,0,0);syscall(11,text,1024,0,0,0,0);return 0;
}
fn vx_contact_stop_check(directory,action) {
    let drive=pj_get(pj_get(ve_state,"controller"),"drive");
    let left=vc_json_int(drive,"leftSpeed",0);let right=vc_json_int(drive,"rightSpeed",0);
    if !cs_observe(vx_contact_guard,1,ve_contact,left,right) {return 0;}
    vx_contact_stop_reason=cs_reason(vx_contact_guard);
    // Request zero before attempting disk I/O. A protocol failure before the
    // echo leaves no report; it is not evidence of a stopped simulator.
    pb_zero(action,8);ve_step(action);
    drive=pj_get(pj_get(ve_state,"controller"),"drive");
    vc_require(!vc_json_int(drive,"leftSpeed",0) && !vc_json_int(drive,"rightSpeed",0),"zero command was not echoed");
    vx_contact_stop_report(directory,vx_contact_stop_reason,1);return 1;
}
'''


def replace_one(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unexpected source shape; refusing transformation')
    return source.replace(old, new, 1)


def transform(chase, main):
    if 'vw_contact_stop' in chase or '--contact-stop' in main:
        raise ValueError('source already contains contact stop')
    chase = replace_one(chase, 'global vw_chase=0;', GLOBALS + 'global vw_chase=0;')
    chase = replace_one(chase, 'fn vx_episode(directory,scene,seed,mode,base,hidden) {',
                        HOOKS + '\nfn vx_episode(directory,scene,seed,mode,base,hidden) {')
    anchor = '    while ve_steps<vw_horizon {\n        if vw_fetch {let cue=0;'
    replacement = ('    vx_contact_stop_reason=0;if vw_contact_stop {if !vx_contact_guard {vx_contact_guard=alloc(24);}'
                   'vc_require(cs_init(vx_contact_guard,3),"contact guard initialization failed");}\n'
                   '    while ve_steps<vw_horizon && !vx_contact_stop_reason {\n'
                   '        if !vw_contact_stop || !vx_contact_stop_check(directory,action) {\n'
                   '        if vw_fetch {let cue=0;')
    chase = replace_one(chase, anchor, replacement)
    chase = replace_one(chase,
                        '    }\n    // Each row\'s weight becomes its discounted return',
                        '        }\n    }\n'
                        '    if vw_contact_stop && !vx_contact_stop_reason && ve_steps==vw_horizon {'
                        'vx_contact_stop_check(directory,action);}\n'
                        '    // Each row\'s weight becomes its discounted return')
    anchor = '    pl_text(b,",\\"blackout\\":");pj_bool_text(b,vw_blackout);'
    replacement = ('    if vw_contact_stop {pl_text(b,",\\"contactStopReason\\":");'
                   'if vx_contact_stop_reason==1 {pj_text(b,"sustained_contact");}'
                   'else if vx_contact_stop_reason==2 {pj_text(b,"invalid_observation");}else {pl_text(b,"null");}'
                   'pl_text(b,",\\"countAsFailedGame\\":");pj_bool_text(b,vx_contact_stop_reason!=0);'
                   'pl_text(b,",\\"fullHorizonCompleted\\":");pj_bool_text(b,!vx_contact_stop_reason && ve_steps==vw_horizon);}\n' + anchor)
    chase = replace_one(chase, anchor, replacement)
    chase = replace_one(chase, 'fn vx_run() {\n    vc_mkdir(vw_output);',
                        'fn vx_run() {\n    vx_contact_stopped_episodes=0;vc_mkdir(vw_output);')
    chase = replace_one(chase, 'vx_episode(directory,vx_scene(episode),seed,mode,0,hidden);reaches=reaches+vx_reaches;',
                        'vx_episode(directory,vx_scene(episode),seed,mode,0,hidden);'
                        'if vx_contact_stop_reason {vx_contact_stopped_episodes=vx_contact_stopped_episodes+1;}reaches=reaches+vx_reaches;')
    chase = replace_one(chase, '    pl_text(s,"{\\"complete\\":true,\\"game\\":\\"chase\\",\\"episodes\\":");',
                        '    pl_text(s,"{\\"complete\\":");pj_bool_text(s,!vx_contact_stopped_episodes);'
                        'if vw_contact_stop {pl_text(s,",\\"contactStoppedEpisodes\\":");pl_int(s,vx_contact_stopped_episodes);}'
                        'pl_text(s,",\\"game\\":\\"chase\\",\\"episodes\\":");')
    main = replace_one(main, 'import "chase.flex";', 'import "contact-stop.flex";\nimport "chase.flex";')
    main = replace_one(main, '        else if pl_equal(flag,"--fetch") {',
                       '        else if pl_equal(flag,"--contact-stop") {vc_require(!vw_contact_stop,"duplicate contact stop");vw_contact_stop=1;}\n'
                       '        else if pl_equal(flag,"--fetch") {')
    anchor = '    vc_require(!vw_level || (vw_fetch'
    guard = ('    vc_require(!vw_contact_stop || (pl_equal(command,"run") && vw_fetch && vw_policy && '
             '!vw_chase_forward && !vw_ensemble_count && !vw_sample_actions && !vw_record_memory),'
             '"contact stop requires an isolated simulated fetch policy run");\n')
    main = replace_one(main, anchor, guard + anchor)
    return chase, main
