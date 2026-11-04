#!/usr/bin/env python3
"""Add an opt-in simulator-only best-effort failure stop to copied sources."""


def replace_one(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unexpected source shape; refusing transformation')
    return source.replace(old, new, 1)


HOST = r'''// Best effort for the virtual simulator only. This is a single nonblocking
// write of command 3, followed by a bounded wait; it is not a stop ACK.
global vc_fault_stop_enabled=0;
global vc_fault_stop_fd=-1;
global vc_fault_stop_pid=0;
global vc_fault_stop_sequence=0;
global vc_fault_stop_attempted=0;
global vc_fault_stop_ready=0;
fn vc_fault_io_now() {return pl_now();}
fn vc_fault_stop() {
    if !vc_fault_stop_enabled || vc_fault_stop_attempted || vc_fault_stop_fd<0 || vc_fault_stop_pid<=0 {return 0;}
    vc_fault_stop_attempted=1;let request=alloc(64);let i=0;
    while i<8 {store64(request+i*8,0);i=i+1;}
    store64(request,3);store64(request+8,vc_fault_stop_sequence+1);
    // MSG_NOSIGNAL | MSG_DONTWAIT; never wait for socket capacity.
    let n=syscall(44,vc_fault_stop_fd,request,64,16448,0,0);syscall(11,request,64,0,0,0,0);
    if n!=64 {pl_print(2,"Simulator failure stop request incomplete or unavailable; stop unverified.\n");return 0;}
    let status=alloc(8);let now=pl_now();let end=now+300;let attempts=0;let reaped=0;let done=0;
    while now>=0 && now<end && attempts<150 && !done {
        let result=syscall(61,vc_fault_stop_pid,status,1,0,0,0);
        if result==vc_fault_stop_pid {reaped=1;done=1;}
        if result<0 && result!= -4 {done=1;}
        if !done {syscall(7,0,0,2,0,0,0);attempts=attempts+1;now=pl_now();}
    }
    syscall(11,status,8,0,0,0,0);
    if reaped {pl_print(2,"Simulator failure stop request sent; child exited, stop unverified.\n");}
    else {pl_print(2,"Simulator failure stop request sent; child exit not observed, stop unverified.\n");}
    return 0;
}
'''


def transform(host, environment, main):
    if 'vc_fault_stop_enabled' in host or '--contact-stop-failsafe' in main:
        raise ValueError('source already contains failure stop')
    host = replace_one(host, 'fn vc_require(ok,message) {if !ok {',
                       HOST + '\nfn vc_require(ok,message) {if !ok {vc_fault_stop();')
    host = replace_one(host, '    let at=0;let deadline=pl_now()+vc_io_timeout;',
        '    let bounded=vc_fault_stop_enabled && vc_fault_stop_ready && fd==vc_fault_stop_fd;'
        'let timeout=vc_io_timeout;if bounded && timeout>5000 {timeout=5000;}\n'
        '    let now=pl_now();if bounded {now=vc_fault_io_now();vc_require(now>=0,"simulator stream clock failure");}'
        'let at=0;let deadline=now+timeout;')
    host = replace_one(host, '    while at<size {let n=0;if reading {n=syscall(0,fd,data+at,size-at,0,0,0);}',
        '    while at<size {if bounded {let current=vc_fault_io_now();'
        'vc_require(current>=0 && current<deadline,"simulator stream deadline or clock failure");}'
        'let n=0;if reading {n=syscall(0,fd,data+at,size-at,0,0,0);}')
    environment = replace_one(environment,
        '    ve_sequence=ve_sequence+1;pb_zero(ve_request,64);store64(ve_request,command);store64(ve_request+8,ve_sequence);',
        '    ve_sequence=ve_sequence+1;vc_fault_stop_sequence=ve_sequence;pb_zero(ve_request,64);store64(ve_request,command);store64(ve_request+8,ve_sequence);')
    environment = replace_one(environment,
        '    ve_process=vc_spawn(args,vc_path(output,"native.log"),0,1);ve_sequence=0;ve_steps=0;',
        '    ve_process=vc_spawn(args,vc_path(output,"native.log"),0,1);'
        'if vc_fault_stop_enabled {vc_fault_stop_fd=load64(ve_process+8);vc_fault_stop_pid=load64(ve_process);vc_fault_stop_sequence=0;vc_fault_stop_attempted=0;vc_fault_stop_ready=0;}'
        've_sequence=0;ve_steps=0;')
    environment = replace_one(environment, '    pb_zero(ve_previous,8);ve_command(1,0,0);ve_check(1);ve_pose_read(ve_state,ve_pose);',
        '    pb_zero(ve_previous,8);ve_command(1,0,0);ve_check(1);'
        'if vc_fault_stop_enabled {vc_fault_stop_ready=1;}ve_pose_read(ve_state,ve_pose);')
    # A clean stop has already been sent. Never send another on later failures.
    environment = replace_one(environment, 'fn ve_close() {ve_command(3,0,0);',
                              'fn ve_close() {vc_fault_stop_fd=-1;ve_command(3,0,0);')
    main = replace_one(main, '        else if pl_equal(flag,"--contact-stop") {',
        '        else if pl_equal(flag,"--contact-stop-failsafe") {vc_require(!vc_fault_stop_enabled,"duplicate failure stop");vc_fault_stop_enabled=1;}\n'
        '        else if pl_equal(flag,"--contact-stop") {')
    main = replace_one(main, '    vc_require(!vw_contact_stop || (pl_equal(command,"run")',
        '    vc_require(!vc_fault_stop_enabled || vw_contact_stop,"failure stop requires contact stop");\n'
        '    vc_require(!vw_contact_stop || (pl_equal(command,"run")')
    return host, environment, main
