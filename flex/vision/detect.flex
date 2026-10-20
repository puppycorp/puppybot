// The policy-facing boundary: RGB observations in, versioned image detections
// out. It carries no world positions, simulator IDs or robot motion commands.
import "image.flex";
import "../../build/flex/detector-model.flex";
global vd_labels=0;
global vd_classes=0;
global vd_threshold=0;
global vd_limit=0;
global vd_scores=0;
global vd_count=0;
global vd_data=0;
global vd_anchors=0;
global vd_input=0;
global vd_preprocess_ms=0;
global vd_inference_ms=0;
fn vd_setup(manifest,kernel,backend) {
    vp_begin(manifest,kernel,backend);let hash=pj_string_field(vp_manifest,"modelSha256");vp_require(!pj_error && pl_equal(hash,pup_detector_source_hash()),"manifest model hash differs from the compiled Pup graph");
    let decoder=pj_string_field(vp_manifest,"decoder");let suppression=pj_string_field(vp_manifest,"suppression");vp_require(!pj_error && pl_equal(decoder,"xyxy-class-scores") && pl_equal(suppression,"none"),"unsupported detection decoder/suppression");
    vd_labels=pj_need(vp_manifest,"classes",3);vd_classes=pj_count(vd_labels);vd_threshold=pj_real(vp_manifest,"confidence");vd_limit=pj_integer(vp_manifest,"maxDetections",1,300);
    vp_require(!pj_error && vd_classes>=1 && vd_classes<=256 && f64_ge(vd_threshold,0x3f50624dd2f1a9fc) && f64_le(vd_threshold,PB_ONE),"invalid classes/confidence/detection limit");let i=0;while i<vd_classes {vp_require(pj_kind(pj_index(vd_labels,i))==2,"class labels must be strings");i=i+1;}
    pup_build_detector();let input=pj_need(vp_manifest,"input",4);let width=pj_integer(input,"width",32,2048);let height=pj_integer(input,"height",32,2048);vp_require(!pj_error && width==vp_dim(vp_input,3) && height==vp_dim(vp_input,2),"manifest image dimensions differ from Pup");
    vp_require(vp_rank(vp_output)==3 && vp_dim(vp_output,0)==1 && vp_dim(vp_output,1)==4+vd_classes,"model output must be [1,4+classes,anchors]");vd_anchors=vp_dim(vp_output,2);vd_data=alloc(load64(vp_output+8)*4);vd_scores=alloc(vd_limit*16);return 0;
}
fn vd_select() {
    vd_count=0;let c=0;
    while c<vd_classes {let a=0;while a<vd_anchors {let score=pb_read_float(vd_data+((c+4)*vd_anchors+a)*4);vp_require(f64_is_finite(score) && f64_ge(score,0) && f64_le(score,PB_ONE),"model returned an invalid class score");
        if f64_ge(score,vd_threshold) {let i=vd_count;if i==vd_limit {i=i-1;if !f64_gt(score,load64(vd_scores+i*16)) {i=-1;}}if i>=0 {while i>0 && f64_gt(score,load64(vd_scores+(i-1)*16)) {pb_copy(vd_scores+i*16,vd_scores+(i-1)*16,16);i=i-1;}store64(vd_scores+i*16,score);store64(vd_scores+i*16+8,c*vd_anchors+a);if vd_count<vd_limit {vd_count=vd_count+1;}}}
        a=a+1;}c=c+1;}
    return 0;
}
fn vd_coordinate(anchor,component,width,height) {let value=pb_read_float(vd_data+(component*vd_anchors+anchor)*4);vp_require(f64_is_finite(value),"model returned a nonfinite box");let offset=vi_left;let limit=width;if component&1 {offset=vi_top;limit=height;}return pb_fclamp(f64_div(f64_sub(value,f64_from_i64(offset)),vi_scale),0,f64_from_i64(limit));}
fn vd_result(b,width,height,frame_id,captured_ms) {
    pl_text(b,"{\"schema\":\"puppybot.detections.v1\",\"model\":{\"id\":");pj_text(b,pj_string_field(vp_manifest,"id"));pl_text(b,",\"graphSha256\":");pj_text(b,pup_detector_source_hash());pl_text(b,",\"weightsSha256\":");pj_text(b,pj_string_field(vp_manifest,"weightsSha256"));pl_text(b,"},\"runtime\":\"pup\",\"backend\":");if vp_backend {pj_text(b,"hip");}else {pj_text(b,"cpu");}
    pl_text(b,",\"frame\":{\"id\":");pl_uint(b,frame_id);pl_text(b,",\"capturedMs\":");pl_uint(b,captured_ms);pl_text(b,",\"width\":");pl_uint(b,width);pl_text(b,",\"height\":");pl_uint(b,height);pl_text(b,"},\"coordinates\":\"image-pixels\",\"preprocessMs\":");pl_uint(b,vd_preprocess_ms);pl_text(b,",\"inferenceMs\":");pl_uint(b,vd_inference_ms);pl_text(b,",\"detections\":[");
    let i=0;let emitted=0;while i<vd_count {let item=vd_scores+i*16;let index=load64(item+8);let class=index/vd_anchors;let anchor=index%vd_anchors;let x1=vd_coordinate(anchor,0,width,height);let y1=vd_coordinate(anchor,1,width,height);let x2=vd_coordinate(anchor,2,width,height);let y2=vd_coordinate(anchor,3,width,height);
        if f64_gt(x2,x1) && f64_gt(y2,y1) {if emitted {pl_char(b,44);}pl_text(b,"{\"classId\":");pl_uint(b,class);pl_text(b,",\"label\":");pj_text(b,pj_value(pj_index(vd_labels,class)));pl_text(b,",\"confidence\":");pl_float(b,load64(item));pl_text(b,",\"box\":[");pl_float(b,x1);pl_char(b,44);pl_float(b,y1);pl_char(b,44);pl_float(b,x2);pl_char(b,44);pl_float(b,y2);pl_text(b,"]}");emitted=emitted+1;}i=i+1;
    }return pl_text(b,"]}\n");
}
fn vd_detect_rgb(rgb,width,height,frame_id,captured_ms,b) {
    vi_dimensions(width,height);if vd_input {syscall(11,vd_input,load64(vp_input+8)*4,0,0,0,0);}let start=pl_now();vd_input=vi_preprocess(rgb,width,height);vd_preprocess_ms=pl_now()-start;vp_upload(load64(vp_input),vd_input,load64(vp_input+8)*4);start=pl_now();vp_execute();vp_read_output(vd_data);vd_inference_ms=pl_now()-start;vd_select();vd_result(b,width,height,frame_id,captured_ms);return !load64(b+24);
}
