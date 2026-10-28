// Replay an audited policy history, then compare a brick patch with a nearby
// control patch under exactly the same feedback and recurrent state.
import "../../../flex/control/verify.flex";
import "../../../flex/control/actions.flex";
fn vs_patch(image,x0,y0) {
    let y=0;while y<6 {let x=0;while x<6 {let c=0;while c<3 {let to=(c*84+y0+y)*84+x0+x;let from=(c*84+y0+y)*84+x0+x+10;store8(image+to,load8(image+from));c=c+1;}x=x+1;}y=y+1;}return 0;
}
fn vs_response(process,image,own,hidden,input,response) {
    vc_policy_input(image,own,hidden,input,0);vc_io(0,load64(process+8),input,(21168+7+128)*4);vc_io(1,load64(process+8),response,135*4);return 0;
}
fn vs_result(b,name,response,decoded) {
    let kind=ca_decode(response,decoded);vc_require(kind>=0,"nonfinite sensitivity response");pl_text(b,"\"");pl_text(b,name);pl_text(b,"\":{\"actionClass\":");pl_int(b,kind);pl_text(b,",\"steering\":");pl_float(b,pb_read_float(decoded));pl_text(b,",\"speed\":");pl_float(b,pb_read_float(decoded+4));pl_text(b,",\"logits\":[");let i=0;while i<7 {if i {pl_char(b,44);}pl_float(b,pb_read_float(response+i*4));i=i+1;}pl_text(b,"]}");return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_pixels_init();vc_require(argc==4,"probe POLICY AUDITED_EPISODE NEW_OUTPUT");let policy=vc_absolute(load64(argv+8));let run=vc_absolute(load64(argv+16));let output=vc_absolute(load64(argv+24));vc_mkdir(output);
    let receipt=vc_json_file(vc_path(policy,"receipt.json"));let sha=vc_string(pj_string_field(receipt,"weightsSHA256"));vc_require(pl_equal(vc_file_sha(vc_path(policy,"weights.bin")),sha) && pl_equal(vc_file_sha(vc_path(policy,"policy")),pj_string_field(receipt,"binarySHA256")),"sensitivity policy hash mismatch");
    let audit=vc_json_file(vc_path(run,"../verified/result.json"));vc_require(pj_boolean(audit,"passed") && !pj_real(audit,"commandReplayMaxAbsError") && pl_equal(pj_string_field(audit,"weightsSHA256"),sha),"sensitivity probe requires audited autonomous history");
    let args=vc_args();vc_add(args,vc_path(policy,"policy"));vc_add(args,vc_path(policy,"weights.bin"));vc_add(args,sha);vc_add(args,vc_path(policy,"kernels"));vc_add(args,"3");vc_add(args,"--raw");let process=vc_spawn(args,vc_path(output,"policy.log"),0,1);let magic=alloc(8);vc_io(1,load64(process+8),magic,8);vc_require(load64(magic)==load64("VCPRAW01"),"sensitivity handshake mismatch");
    let hidden=alloc(512);let input=alloc((21168+7+128)*4);let clean=alloc(135*4);let changed=alloc(135*4);let decoded=alloc(8);let altered=alloc(21168);let text=alloc(8192);let b=alloc(32);pl_builder(b,text,8192);let initial=vc_json_file(vc_path(run,"initial.json"));let frame=vc_json_int(initial,"totalSteps",0);va_lines(vc_path(run,"decisions.jsonl"));let row=va_next();let count=0;let tested=0;
    while row {vc_require(count<512,"sensitivity history exceeds task bound");let rgb=vc_map(vc_path(run,vc_concat("actor-",vc_concat(vc_int(frame),".rgb"))));vc_require(vc_size==21168,"invalid saved actor RGB");let own=vc_map(vc_path(run,vc_concat("actor-",vc_concat(vc_int(frame),".feedback"))));vc_require(vc_size==28 && !pb_u32(own+24),"invalid own feedback");vs_response(process,rgb,own,hidden,input,clean);let kind=ca_decode(clean,decoded);let action=pj_get(row,"action");vc_require(kind>=0 && pb_u32(decoded)==pb_f64_to_f32(pj_real_node(pj_index(action,0))) && pb_u32(decoded+4)==pb_f64_to_f32(pj_real_node(pj_index(action,1))),"sensitivity replay action differs from autonomous history");
        if frame==1005 {vc_require(!tested,"duplicate sensitivity frame");tested=1;pl_text(b,"{\"weightsSHA256\":");pj_text(b,sha);pl_text(b,",\"frame\":1005,\"note\":\"Offline single-frame patch intervention on exact recurrent state; action replay uses original image\",\"targetPatchXYWH\":[10,12,6,6],\"controlPatchXYWH\":[22,12,6,6],");vs_result(b,"original",clean,decoded);vc_copy(altered,rgb,21168);vs_patch(altered,10,12);vs_response(process,altered,own,hidden,input,changed);pl_char(b,44);vs_result(b,"targetPatchReplaced",changed,decoded);vc_copy(altered,rgb,21168);vs_patch(altered,22,12);vs_response(process,altered,own,hidden,input,changed);pl_char(b,44);vs_result(b,"controlPatchReplaced",changed,decoded);pl_text(b,",\"actualCommandsReplayedExactly\":true}\n");}
        vc_copy(hidden,clean+28,512);syscall(11,rgb,21168,0,0,0,0);syscall(11,own,28,0,0,0,0);frame=vc_json_int(row,"step",0);count=count+1;row=va_next();
    }
    vc_require(tested && !load64(b+24),"sensitivity frame missing or result overflow");vc_finish(process,15000);vc_write(vc_path(output,"result.json"),text,load64(b+8));return 0;
}
