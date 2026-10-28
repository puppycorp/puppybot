// Offline evaluator: reference positions never enter the policy or its state.
import "../../../flex/control/verify.flex";
fn bd_distance(state,target,pose) {
    ve_pose_read(state,pose);return ve_distance(pose,target);
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"measure-brick-distance EPISODE OUTPUT");let episode=vc_absolute(load64(argv+8));let output=vc_absolute(load64(argv+16));vc_mkdir(output);
    let state=vc_json_file(vc_path(episode,"initial.json"));let objects=pj_get(pj_get(state,"case"),"objects");vc_require(pj_kind(objects)==3 && pj_count(objects)==1,"distance metric requires exactly one brick");let target=alloc(24);let pose=alloc(24);va_vector(pj_get(pj_index(objects,0),"position"),target,3);
    let minimum=bd_distance(state,target,pose);let best_step=0;let observations=1;let consumed=0;va_lines(vc_path(episode,"decisions.jsonl"));let row=va_next();
    while row && !consumed {
        state=pj_get(row,"state");consumed=vc_json_int(state,"findReturn","consumedIndex")>=0;
        va_vector(pj_get(pj_index(pj_get(pj_get(state,"case"),"objects"),0),"position"),target,3);
        let distance=bd_distance(state,target,pose);observations=observations+1;if f64_lt(distance,minimum) {minimum=distance;best_step=observations-1;}row=va_next();
    }
    vc_require(observations>=2,"recorded episode has no commands");let text=alloc(2048);let b=alloc(32);pl_builder(b,text,2048);
    pl_text(b,"{\"evaluationOnly\":true,\"runtime\":\"Flexscript\",\"referencePositionsEnteredActor\":false,\"observedDecisionFrames\":");pl_int(b,observations);
    pl_text(b,",\"closestPlanarBaseToBrickM\":");pl_float(b,minimum);pl_text(b,",\"closestAtAction\":");pl_int(b,best_step);
    pl_text(b,",\"consumed\":");pj_bool_text(b,consumed);pl_text(b,",\"decisionsSHA256\":");pj_text(b,vc_file_sha(vc_path(episode,"decisions.jsonl")));pl_text(b,"}\n");
    vc_require(!load64(b+24),"distance report exceeded limit");vc_write(vc_path(output,"result.json"),text,load64(b+8));pl_write(1,text,load64(b+8));return 0;
}
