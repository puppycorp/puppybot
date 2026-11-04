// Staged actor-boundary recorder. Not imported by the current control path.
// A future instrumented single-policy run must call pa_record after policy
// inference and final action selection, before the environment advances. The
// image is the uint8 actor image and input is the exact float32 buffer sent to the policy;
// output is the raw two-action-plus-memory float32 response. This records
// bytes, not a claim that a particular executable or argv was used.
import "host.flex";

// Context slots: fd, seed, horizon, image bytes, memory width, count,
// previous sequence and previous frame. Header/record integers are i64 LE.
fn pa_open(path,seed,horizon,image_bytes,memory_width) {
    vc_require(path && seed>=0 && horizon>0 && horizon<=512 && (image_bytes==21168 || image_bytes==49152) && (memory_width==128 || memory_width==256),"invalid actor attestation configuration");
    let fd=syscall(2,path,0x800c1,384,0,0,0);vc_require(fd>=0,"actor attestation output must be new");
    let context=alloc(64);store64(context,fd);store64(context+8,seed);store64(context+16,horizon);store64(context+24,image_bytes);store64(context+32,memory_width);store64(context+40,0);store64(context+48,-1);store64(context+56,-1);
    let header=alloc(56);store64(header,load64("PBATST01"));store64(header+8,1);store64(header+16,seed);store64(header+24,horizon);store64(header+32,image_bytes);store64(header+40,memory_width);store64(header+48,image_bytes+(image_bytes+7+memory_width)*4+(2+memory_width)*4+32);
    vc_require(!pl_write(fd,header,56),"cannot write actor attestation header");syscall(11,header,56,0,0,0,0);return context;
}
fn pa_record(context,index,sequence,frame,image,input,output,action) {
    vc_require(context && image && input && output && action,"missing actor attestation buffer");let fd=load64(context);let count=load64(context+40);
    vc_require(fd>=0 && index==count && count<load64(context+16) && sequence>load64(context+48) && frame>load64(context+56),"invalid actor attestation order");
    let record=alloc(24);store64(record,index);store64(record+8,sequence);store64(record+16,frame);let input_size=(load64(context+24)+7+load64(context+32))*4;let output_size=(2+load64(context+32))*4;
    vc_require(!pl_write(fd,record,24) && !pl_write(fd,image,load64(context+24)) && !pl_write(fd,input,input_size) && !pl_write(fd,output,output_size) && !pl_write(fd,action,8),"cannot write actor attestation record");
    syscall(11,record,24,0,0,0,0);store64(context+40,count+1);store64(context+48,sequence);store64(context+56,frame);return 0;
}
fn pa_finish(context) {
    vc_require(context && load64(context)>=0 && load64(context+40)==load64(context+16),"incomplete actor attestation");
    let footer=alloc(16);store64(footer,load64("PBDONE01"));store64(footer+8,load64(context+40));vc_require(!pl_write(load64(context),footer,16),"cannot write actor attestation footer");syscall(11,footer,16,0,0,0,0);vc_require(!syscall(3,load64(context),0,0,0,0,0),"cannot close actor attestation");store64(context,-1);return 0;
}
