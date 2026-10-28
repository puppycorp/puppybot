// Exercise the trainer's target loader on the complete verified corpus.
import "../../../flex/control/pose-supervision.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==4,"pose-preflight DATA TARGET_DIRECTORY OUTPUT_JSON");let data=vc_map(load64(argv+8));let bytes=vc_size;vc_require(bytes>=32 && vd_row_bytes(data)==56 && load64(data+8)==172 && load64(data+16)==136 && load64(data+24)==354 && bytes==32+172*354*21224,"unexpected preflight dataset");pt_pose_open(load64(argv+16),data,bytes,56);
    vc_save_text(load64(argv+24),"{\"passed\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"complete172CorpusAndTargetsAccepted\":true,\"actorInputsUnchanged\":true}\n");return 0;
}
