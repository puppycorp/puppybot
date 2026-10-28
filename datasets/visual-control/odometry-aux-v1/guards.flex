// Deliberate role, temporal-alignment and padding corruption must be rejected.
import "../../../flex/control/host.flex";
fn og_contains(text,part) {let i=0;while load8(text+i) {if pl_starts(text+i,part) {return 1;}i=i+1;}return 0;}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==6,"pose-guards TOOL DATA RUNS TARGETS NEW_OUTPUT");let tool=vc_absolute(load64(argv+8));let data=vc_absolute(load64(argv+16));let runs=vc_absolute(load64(argv+24));let source=vc_map(load64(argv+32));let bytes=vc_size;vc_require(bytes==32+172*354*20 && load64(source)==load64("PVPOSE01"),"invalid pose guard source");let output=vc_absolute(load64(argv+40));vc_mkdir(output);let altered=alloc(bytes);let variant=0;
    while variant<3 {vc_copy(altered,source,bytes);let name="wrong-role";let expected="pose target dimensions or fit-validation roles differ";
        if !variant {store64(altered+16,135);}
        else if variant==1 {name="shifted-frame";expected="pose target does not match its pre-action physical trace frame";let t=1;let changed=0;while t<354 && !changed {let current=source+32+t*20;let previous=current-20;if pb_u32(current+16) && pb_u32(previous+16) {let i=0;while i<16 {if load8(current+i)!=load8(previous+i) {changed=1;}i=i+1;}if changed {vc_copy(altered+32+t*20,previous,16);}}t=t+1;}vc_require(changed,"pose guard could not find a moving pre-action frame");}
        else {name="nonzero-padding";expected="pose target padding is not zero";let t=0;while t<172*354 && pb_u32(source+32+t*20+16) {t=t+1;}vc_require(t<172*354,"pose guard source has no padding");pb_put32(altered+32+t*20,0x3f800000);}
        let path=vc_path(output,vc_concat(name,".bin"));vc_write(path,altered,bytes);let result=vc_path(output,vc_concat(name,"-result.json"));let log=vc_path(output,vc_concat(name,".log"));let args=vc_args();vc_add(args,tool);vc_add(args,"verify");vc_add(args,data);vc_add(args,runs);vc_add(args,path);vc_add(args,result);let status=vc_reap(vc_spawn(args,log,0,0),60000);vc_require(status>0 && og_contains(vc_text_file(log),expected),"corrupted pose supervision was not rejected for the expected reason");vc_require(syscall(21,result,4,0,0,0,0),"corrupted pose labels published a positive verification receipt");variant=variant+1;
    }
    vc_save_text(vc_path(output,"result.json"),"{\"passed\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"changedSplitRoleRejected\":true,\"oneFrameMisalignmentRejected\":true,\"nonzeroPaddingRejected\":true}\n");return 0;
}
