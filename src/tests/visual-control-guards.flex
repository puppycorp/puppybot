// Native malformed-demonstration checks run the real trainer as a child.
import "../control/host.flex";
fn vg_contains(text,part) {let i=0;while load8(text+i) {if pl_starts(text+i,part) {return 1;}i=i+1;}return 0;}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==4,"visual-control-guards TRAINER KERNEL_DIRECTORY NEW_OUTPUT_DIRECTORY");let output=vc_absolute(load64(argv+24));vc_mkdir(output);
    let seed=alloc(32);vc_copy(seed,"PUPV0001",8);store64(seed+16,32);let seed_path=vc_path(output,"seed.bin");vc_write(seed_path,seed,32);let sha=vc_file_sha(seed_path);
    let names=vc_args();vc_add(names,"nonfinite");vc_add(names,"task-hint");vc_add(names,"action-bound");vc_add(names,"sequence-limit");vc_add(names,"batch-sequence-limit");let messages=vc_args();vc_add(messages,"nonfinite demonstration value");vc_add(messages,"task-event feedback must be masked");vc_add(messages,"demonstration action exceeds");vc_add(messages,"invalid demonstration dimensions");vc_add(messages,"invalid demonstration dimensions");let i=0;
    while i<5 {
        let directory=vc_path(output,load64(names+8+i*8));vc_mkdir(directory);let size=32+2*(21168+44);let data=alloc(size);vc_copy(data,"PVDATA01",8);store64(data+8,2);store64(data+16,1);store64(data+24,1);
        pb_put32(data+32+21168+40,0x3f800000);pb_put32(data+32+(21168+44)+21168+40,0x3f800000);let index=0;let value=0x7fc00000;if i==1 {index=6;value=0x3f800000;}if i==2 {index=7;value=0x40000000;}
        pb_put32(data+32+21168+index*4,value);let path=vc_path(directory,"data.bin");vc_write(path,data,size);let args=vc_args();vc_add(args,vc_absolute(load64(argv+8)));vc_add(args,seed_path);vc_add(args,sha);vc_add(args,vc_absolute(load64(argv+16)));vc_add(args,path);vc_add(args,directory);vc_add(args,"0");vc_add(args,"1");vc_add(args,"100");vc_add(args,"7");vc_add(args,"--random");
        if i==3 {store64(data+24,513);vc_write(path,data,size);}if i==4 {store64(data+24,129);vc_write(path,data,size);store64(args+8+7*8,"8");}
        let log=vc_path(directory,"trainer.log");let process=vc_spawn(args,log,0,0);let status=vc_reap(process,30000);vc_require(status>0 && vg_contains(vc_text_file(log),load64(messages+8+i*8)),"native malformed data was not rejected for the expected reason");vc_require(syscall(21,vc_path(directory,"weights.bin"),4,0,0,0,0),"invalid data published a policy checkpoint");i=i+1;
    }
    vc_save_text(vc_path(output,"result.json"),"{\"passed\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"nativeTrainerRejects\":[\"nonfinite feedback\",\"task-event hints\",\"out-of-range actions\",\"oversized sequence\",\"oversized batch sequence\"]}\n");pl_print(1,"Native trainer malformed-data guards passed.\n");return 0;
}
