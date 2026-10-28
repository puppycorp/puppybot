// Exercise real mappings, packing and trainer guards above the former 1 GiB limit.
import "../control/dataset.flex";
fn vs_contains(text,part) {let i=0;while load8(text+i) {if pl_starts(text+i,part) {return 1;}i=i+1;}return 0;}
fn vs_sparse(path,size) {
    let fd=syscall(2,path,0x800c2,384,0,0,0);vc_require(fd>=0 && !syscall(77,fd,size,0,0,0,0),"cannot create sparse dataset");return fd;
}
fn vs_trainer(trainer,seed,sha,kernels,data,out) {
    let args=vc_args();vc_add(args,trainer);vc_add(args,seed);vc_add(args,sha);vc_add(args,kernels);vc_add(args,data);vc_add(args,out);vc_add(args,"0");vc_add(args,"1");vc_add(args,"100");vc_add(args,"7");vc_add(args,"--random");vc_add(args,"--categorical");return args;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==5,"visual-control-size CONTROL TRAINER KERNELS NEW_OUTPUT");let control=vc_absolute(load64(argv+8));let trainer=vc_absolute(load64(argv+16));let kernels=vc_absolute(load64(argv+24));let output=vc_absolute(load64(argv+32));vc_mkdir(output);
    let n=144;let length=354;let stride=length*21224;let size=32+n*stride;vc_require(size>1073741824 && size<VC_MAX_FILE_BYTES,"test does not cross old reader bound");let path=vc_path(output,"large.bin");let fd=vs_sparse(path,size);let data=syscall(9,0,size,3,1,fd,0);vc_require(data>0,"cannot map sparse dataset");vc_copy(data,"PVDATA03",8);store64(data+8,n);store64(data+16,n-1);store64(data+24,length);let i=0;
    while i<n {let row=data+32+i*stride+length*21168;pb_put32(row+32,0x3f800000);pb_put32(row+40,0x3f800000);pb_put32(row+44,0x3f800000);pb_put32(row+52,0x3f800000);i=i+1;}
    vc_require(!syscall(26,data,size,4,0,0,0),"cannot sync sparse dataset");syscall(11,data,size,0,0,0,0);syscall(3,fd,0,0,0,0,0);
    data=vc_map(path);vc_require(vc_size==size && load64(data+8)==n && pb_u32(data+32+(n-1)*stride+length*21168+44)==0x3f800000,"large mapping lost final episode");syscall(11,data,size,0,0,0,0);
    let packed=vc_path(output,"packed");let args=vc_args();vc_add(args,control);vc_add(args,"pack-data");vc_add(args,"--data");vc_add(args,path);vc_add(args,"--output");vc_add(args,packed);vc_finish(vc_spawn(args,vc_path(output,"pack.log"),0,0),60000);
    data=vc_map(vc_path(packed,"data.bin"));vc_require(load64(data+8)==n && load64(data+16)==n-1 && load64(data+24)==1 && vc_size==32+n*21224,"large packing changed histories or split");i=0;while i<n {let row=data+32+i*21224+21168;vc_require(pb_u32(row+32)==0x3f800000 && pb_u32(row+40)==0x3f800000 && pb_u32(row+44)==0x3f800000 && pb_u32(row+52)==0x3f800000,"large packing lost labels or commands");i=i+1;}syscall(11,data,vc_size,0,0,0,0);
    let seed=alloc(32);vc_copy(seed,"PUPV0001",8);store64(seed+16,32);let seed_path=vc_path(output,"seed.bin");vc_write(seed_path,seed,32);let sha=vc_file_sha(seed_path);let trained=vc_path(output,"trained");vc_mkdir(trained);vc_finish(vc_spawn(vs_trainer(trainer,seed_path,sha,kernels,path,trained),vc_path(output,"train.log"),0,0),60000);vc_require(!syscall(21,vc_path(trained,"last.bin"),4,0,0,0,0),"large dataset did not complete native forward/validation");
    let excessive=vc_path(output,"excessive.bin");fd=vs_sparse(excessive,VC_MAX_FILE_BYTES+1);syscall(3,fd,0,0,0,0,0);let rejected=vc_path(output,"rejected");vc_mkdir(rejected);let log=vc_path(output,"rejected-train.log");let status=vc_reap(vc_spawn(vs_trainer(trainer,seed_path,sha,kernels,excessive,rejected),log,0,0),30000);vc_require(status>0 && vs_contains(vc_text_file(log),"outside 32 B..2 GiB"),"trainer did not enforce 2 GiB bound");vc_require(syscall(21,vc_path(rejected,"initial.bin"),4,0,0,0,0),"oversized data reached model initialization");
    args=vc_args();vc_add(args,control);vc_add(args,"pack-data");vc_add(args,"--data");vc_add(args,excessive);vc_add(args,"--output");vc_add(args,vc_path(output,"rejected-pack"));log=vc_path(output,"rejected-pack.log");status=vc_reap(vc_spawn(args,log,0,0),30000);vc_require(status>0 && vs_contains(vc_text_file(log),"outside 1 B..2 GiB"),"workflow mapper did not enforce 2 GiB bound");
    vc_save_text(vc_path(output,"result.json"),"{\"passed\":true,\"runtime\":\"Flexscript/Pup CUDA\",\"pythonRequired\":false,\"validDatasetAbove1GiBMappedPackedAndForwarded\":true,\"all144HistoriesAndSplitsPreserved\":true,\"trainerAndWorkflowRejectAbove2GiB\":true}\n");pl_print(1,"Native large-dataset bounds passed.\n");return 0;
}
