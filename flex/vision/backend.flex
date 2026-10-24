// Detector manifest validation. Pup execution/device policy is shared.
import "../ml/runtime.flex";
import "../host/json.flex";
global vp_manifest=0;
global vp_root=0;
global vp_ordinal=0;
fn vp_begin(manifest,kernel,backend) {
    vp_init(kernel,backend,vp_ordinal);let data=alloc(65537);let n=pl_read_file(manifest,data,65536);vp_require(n>0,"cannot read model manifest");vp_manifest=pj_parse(data,n);vp_require(vp_manifest,"invalid model manifest");
    let schema=pj_string_field(vp_manifest,"schema");let runtime=pj_string_field(vp_manifest,"runtime");vp_require(!pj_error && pl_equal(schema,"puppybot.detector.v1") && pl_equal(runtime,"pup"),"unsupported model manifest/runtime");
    let slash=pl_size(manifest);while slash && load8(manifest+slash-1)!=47 {slash=slash-1;}vp_root=alloc(slash+2);if slash {pb_copy(vp_root,manifest,slash);}else {pb_copy(vp_root,".",2);}
    let weight=pj_string_field(vp_manifest,"weights");let sha=pj_string_field(vp_manifest,"weightsSha256");vp_require(!pj_error,"missing checkpoint path or hash");vp_checkpoint_open(vp_path(vp_root,weight),sha);
    return 0;
}
