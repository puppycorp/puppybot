#!/usr/bin/env python3
"""Instrument a private trainer copy with a consumed-batch mirror journal."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unexpected paired trainer source anchor')
    return source.replace(old, new, 1)


def transform(source):
    helper = '''// Private fixed-epoch research journal. It records the host batch that
// is about to be sent, not proof that a GPU kernel consumed that batch.
global ptj_fd=-1;
global ptj_active=0;
global ptj_ids=0;
global ptj_start=-1;
global ptj_count=0;
global ptj_mask=0;
global ptj_next=0;
global ptj_batches=0;
fn ptj_begin(path,seed,episodes,training_count,epochs) {
    vp_require(ptj_fd<0 && !ptj_active && episodes==1031 && training_count==935 && epochs==1 && seed==7120000 && pt_batch==2 && pt_mirror_augment && !pt_focus_copies && !pt_feedback_drop_milli && !pt_max_optimizer_steps,"mirror journal requires fixed paired training schedule");
    ptj_fd=syscall(2,path,0x800c1,384,0,0,0);vp_require(ptj_fd>=0,"cannot create mirror journal");
    if !ptj_ids {ptj_ids=alloc(16);}ptj_active=1;ptj_start=-1;ptj_next=0;ptj_batches=0;
    let header=alloc(40);store64(header,load64("PBMIRR01"));store64(header+8,1);store64(header+16,seed);store64(header+24,training_count);store64(header+32,pt_batch);
    vp_require(!pl_write(ptj_fd,header,40),"cannot write mirror journal header");syscall(11,header,40,0,0,0,0);return 0;
}
fn ptj_fill(order,start,count,mask) {
    if !ptj_active {return 0;}vp_require(order && count>=1 && count<=2 && start>=0 && start+count<=935 && mask>=0 && mask<(1<<count),"invalid mirror journal fill");
    store64(ptj_ids,load64(order+start*8));store64(ptj_ids+8,-1);if count==2 {store64(ptj_ids+8,load64(order+(start+1)*8));}
    ptj_start=start;ptj_count=count;ptj_mask=mask;return 0;
}
fn ptj_send() {
    if !ptj_active {return 0;}vp_require(ptj_start==ptj_next && ptj_count==pb_min(2,935-ptj_next) && ptj_mask==load64(pt_mirror_mask_host),"mirror journal send differs from filled batch");
    let row=alloc(48);store64(row,ptj_batches);store64(row+8,ptj_start);store64(row+16,ptj_count);store64(row+24,ptj_mask);store64(row+32,load64(ptj_ids));store64(row+40,load64(ptj_ids+8));
    vp_require(!pl_write(ptj_fd,row,48),"cannot write mirror journal row");syscall(11,row,48,0,0,0,0);
    ptj_next=ptj_next+ptj_count;ptj_batches=ptj_batches+1;ptj_start=-1;return 0;
}
fn ptj_finish() {
    vp_require(ptj_active && ptj_fd>=0 && ptj_next==935 && ptj_batches==468 && ptj_start<0,"incomplete mirror journal");
    let footer=alloc(16);store64(footer,load64("PBDONE01"));store64(footer+8,ptj_batches);vp_require(!pl_write(ptj_fd,footer,16),"cannot write mirror journal footer");
    syscall(11,footer,16,0,0,0,0);vp_require(!syscall(3,ptj_fd,0,0,0,0,0),"cannot close mirror journal");ptj_fd=-1;ptj_active=0;return 0;
}
'''
    source = once(source, 'fn pt_data_open(path) {', helper + '\nfn pt_data_open(path) {')
    source = once(source, '    }pt_fill_feedback=feedback_mask;pt_fill_count=count;return 0;',
                  '    }ptj_fill(order,start,count,mirror_mask);pt_fill_feedback=feedback_mask;pt_fill_count=count;return 0;')
    source = once(source, 'fn pt_batch_send() {\n    let feedback_mask=pt_fill_feedback;',
                  'fn pt_batch_send() {\n    ptj_send();\n    let feedback_mask=pt_fill_feedback;')
    source = once(source, '        let total=0;let batches=0;let start=0;pt_mirror_active=pt_mirror_augment;pt_feedback_drop_active=pt_feedback_drop_milli;',
                  '        ptj_begin(vp_path(output,"batch-schedule.bin"),seed,episodes,training_count,epochs);\n        let total=0;let batches=0;let start=0;pt_mirror_active=pt_mirror_augment;pt_feedback_drop_active=pt_feedback_drop_milli;')
    source = once(source, '        let validation=0;let validation_batches=0;start=training_count;pt_mirror_active=0;pt_feedback_drop_active=0;',
                  '        ptj_finish();\n        let validation=0;let validation_batches=0;start=training_count;pt_mirror_active=0;pt_feedback_drop_active=0;')
    return source
