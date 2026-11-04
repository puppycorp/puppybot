// Private collector-only map and teacher-label journal. The map is copied at
// the same loop boundary as the actor input; this does not prove map truth.
import "host.flex";

// Context slots: fd, seed, horizon, count, last sequence and last frame.
fn prb_open(path,seed,horizon) {
    vc_require(path && seed>=0 && horizon>0 && horizon<=512,"invalid parent boundary configuration");
    let fd=syscall(2,path,0x800c1,384,0,0,0);vc_require(fd>=0,"parent boundary output must be new");
    let context=alloc(48);store64(context,fd);store64(context+8,seed);store64(context+16,horizon);store64(context+24,0);store64(context+32,-1);store64(context+40,-1);
    let header=alloc(40);store64(header,load64("PBMAPB01"));store64(header+8,1);store64(header+16,seed);store64(header+24,horizon);store64(header+32,176);
    vc_require(!pl_write(fd,header,40),"cannot write parent boundary header");syscall(11,header,40,0,0,0,0);return context;
}
fn prb_record(context,index,sequence,frame,map,label) {
    vc_require(context && map && label,"missing parent boundary buffer");let count=load64(context+24);
    vc_require(load64(context)>=0 && index==count && count<load64(context+16) && sequence>load64(context+32) && frame>load64(context+40),"invalid parent boundary order");
    let row=alloc(24);store64(row,index);store64(row+8,sequence);store64(row+16,frame);
    vc_require(!pl_write(load64(context),row,24) && !pl_write(load64(context),map,144) && !pl_write(load64(context),label,8),"cannot write parent boundary record");
    syscall(11,row,24,0,0,0,0);store64(context+24,count+1);store64(context+32,sequence);store64(context+40,frame);return 0;
}
fn prb_finish(context) {
    vc_require(context && load64(context)>=0 && load64(context+24)==load64(context+16),"incomplete parent boundary");
    let footer=alloc(16);store64(footer,load64("PBDONE01"));store64(footer+8,load64(context+24));vc_require(!pl_write(load64(context),footer,16),"cannot write parent boundary footer");
    syscall(11,footer,16,0,0,0,0);vc_require(!syscall(3,load64(context),0,0,0,0,0),"cannot close parent boundary");store64(context,-1);return 0;
}
