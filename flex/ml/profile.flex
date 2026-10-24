// Profile the linked Pup factory with resident input bindings and a device plan.
import "runtime.flex";
import "../../build/flex/detector-model.flex";
fn pp_now() {syscall(228,1,pl_clock,0,0,0,0);return load64(pl_clock)*1000000000+load64(pl_clock+8);}
fn pp_launch(t,index) {
    if vp_plan_before {vp_plan_pack_launch(load64(vp_plan_before+index*16));vp_plan_pack_launch(load64(vp_plan_before+index*16+8));}
    return vp_check(device_dispatch(load64(t+120),load64(t+112),load64(t+104)));
}
fn pp_hash(path) {let image=vp_map(path);let size=vp_bytes;let hash=vp_digest(image,size);syscall(11,image,size,0,0,0,0);return hash;}
fn pp_report(index,milliseconds,plan,plan_hash,suffix,mode) {
    let entry=plan+80+index*128;let kernel_hash=pp_hash(vp_path(vp_kernel_root,vp_suffix(entry,suffix)));let prepare_hash="";if load64(entry+104)&4 {prepare_hash=pp_hash(vp_path(vp_kernel_root,vp_suffix(vp_suffix(entry,"-input"),suffix)));}
    let text=alloc(4096);let builder=alloc(32);pl_builder(builder,text,4096);pl_text(builder,"{\"index\":");pl_uint(builder,index);pl_text(builder,",\"ms\":");pl_float(builder,milliseconds);pl_text(builder,",\"mode\":\"");pl_text(builder,mode);pl_text(builder,"\",\"backend\":\"");pl_text(builder,vp_backend_name());pl_text(builder,"\",\"planSha256\":\"");pl_text(builder,plan_hash);pl_text(builder,"\",\"kernelSha256\":\"");pl_text(builder,kernel_hash);pl_text(builder,"\",\"prepareSha256\":\"");pl_text(builder,prepare_hash);pl_text(builder,"\"}\n");vp_require(!load64(builder+24),"profile record exceeds output buffer");pl_print(1,text);return 0;
}
fn pp_graph(plan,plan_hash,suffix) {
    let count=load64(vp_nodes);let samples=8;let starts=alloc(count*samples*8);let ends=alloc(count*samples*8);let sample=0;
    while sample<samples {let i=0;while i<count {if load64(vp_at(vp_nodes,i)+120) {let at=(sample*count+i)*8;store64(starts+at,device_event());store64(ends+at,device_event());}i=i+1;}sample=sample+1;}
    vp_check(device_capture_begin(vp_stream));sample=0;
    while sample<samples {let i=0;while i<count {let t=vp_at(vp_nodes,i);if load64(t+120) {let at=(sample*count+i)*8;
        // CU_EVENT_RECORD_EXTERNAL=1 retains timestamp nodes during capture.
        vp_check(cuda_call("cuEventRecordWithFlags",load64(starts+at),vp_stream,1,0,0,0));pp_launch(t,i);vp_check(cuda_call("cuEventRecordWithFlags",load64(ends+at),vp_stream,1,0,0,0));
    }i=i+1;}sample=sample+1;}
    let graph=device_capture_end(vp_stream);vp_require(graph,device_error());let instance=device_graph_instance(graph);vp_require(instance,device_error());vp_check(device_graph_close(graph));vp_check(device_graph_upload(instance,vp_stream));vp_check(device_stream_wait(vp_stream));
    vp_check(device_graph_launch(instance,vp_stream));vp_check(device_stream_wait(vp_stream));vp_check(device_graph_launch(instance,vp_stream));vp_check(device_stream_wait(vp_stream));
    let i=0;while i<count {if load64(vp_at(vp_nodes,i)+120) {let best=0x7f800000;sample=0;
        while sample<samples {let at=(sample*count+i)*8;let elapsed=device_event_elapsed_f32(load64(starts+at),load64(ends+at));vp_check(cuda_status);vp_require(elapsed>0 && elapsed<0x7f800000,"invalid graph event timing");if elapsed<best {best=elapsed;}sample=sample+1;}
        pp_report(i,pb_f32_to_f64(best),plan,plan_hash,suffix,"graph");
    }i=i+1;}
    vp_check(device_graph_instance_close(instance));sample=0;while sample<samples {i=0;while i<count {let at=(sample*count+i)*8;if load64(starts+at) {vp_check(device_event_close(load64(ends+at)));vp_check(device_event_close(load64(starts+at)));}i=i+1;}sample=sample+1;}return 0;
}
fn main(argc,argv) {
    pl_init();let offset=0;if argc>1 && pl_equal(load64(argv+8),"--graph") {offset=1;}
    if argc<6+offset {pl_print(2,"Usage: pup-profile [--graph] BACKEND KERNELDIR WEIGHTS.bin WEIGHTS_SHA256 INPUT.bin [INPUT.bin...]\n");return 2;}
    let backend=vp_backend_parse(load64(argv+(1+offset)*8));vp_require(backend==2 || backend==3,"profiling requires cuda or sass");
    vp_init(load64(argv+(2+offset)*8),backend,0);vp_checkpoint_open(load64(argv+(3+offset)*8),load64(argv+(4+offset)*8));pup_build_model();vp_require(argc==5+offset+load64(vp_inputs),"provide one FP32 input file per model binding");
    let i=0;while i<load64(vp_inputs) {let t=vp_at(vp_at(vp_inputs,i),1);let bytes=load64(t+8)*4;let input=alloc(bytes+1);vp_require(pl_read_file(load64(argv+(5+offset+i)*8),input,bytes+1)==bytes,"input tensor size differs from model binding");vp_upload(load64(t),input,bytes);i=i+1;}
    let warmup=pp_now();i=0;while i<3 || pp_now()-warmup<500000000 {vp_execute();i=i+1;}
    vp_require(vp_active_plan,"profiling requires a Pup schedule");let plan=vp_map(vp_active_plan);let plan_hash=vp_digest(plan,vp_bytes);
    let suffix=".ptx";if backend==3 {suffix=".cubin";}if offset {return pp_graph(plan,plan_hash,suffix);}let begin=device_event();let end=device_event();i=0;
    while i<load64(vp_nodes) {let t=vp_at(vp_nodes,i);
        if load64(t+120) {
            vp_check(device_capture_begin(vp_stream));let n=0;while n<32 {pp_launch(t,i);n=n+1;}
            let graph=device_capture_end(vp_stream);vp_require(graph,device_error());let instance=device_graph_instance(graph);vp_require(instance,device_error());vp_check(device_graph_close(graph));vp_check(device_graph_upload(instance,vp_stream));vp_check(device_stream_wait(vp_stream));
            vp_check(device_graph_launch(instance,vp_stream));vp_check(device_stream_wait(vp_stream));let sample=0;let best=0x7f800000;
            while sample<3 {vp_check(device_event_record(begin,vp_stream));vp_check(device_graph_launch(instance,vp_stream));vp_check(device_event_record(end,vp_stream));vp_check(device_event_wait(end));let elapsed=device_event_elapsed_f32(begin,end);if elapsed<best {best=elapsed;}sample=sample+1;}
            pp_report(i,f64_div(pb_f32_to_f64(best),f64_from_i64(32)),plan,plan_hash,suffix,"hot");vp_check(device_graph_instance_close(instance));
        }i=i+1;
    }vp_check(device_event_close(end));vp_check(device_event_close(begin));return 0;
}
