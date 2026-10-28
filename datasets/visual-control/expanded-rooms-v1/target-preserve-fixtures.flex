// Construct positive and corrupted fixtures for the target-preservation check.
import "../../../flex/control/host.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"target-preserve-fixtures OLD_TARGETS OUTPUT");let old=vc_map(vc_absolute(load64(argv+8)));let bytes=vc_size;let length=load64(old+24);vc_require(load64(old)==load64("PVVIS001") && load64(old+8)==172 && load64(old+16)==136 && length==354 && bytes==32+172*length*12,"unexpected original target fixture");
    let size=32+202*length*12;let next=alloc(size);vc_copy(next,"PVVIS001",8);store64(next+8,202);store64(next+16,160);store64(next+24,length);let i=0;while i<172 {let target=i;if i>=136 {target=i+24;}vc_copy(next+32+target*length*12,old+32+i*length*12,length*12);i=i+1;}
    let output=vc_absolute(load64(argv+16));vc_mkdir(output);vc_write(vc_path(output,"matching.bin"),next,size);let offset=32+160*length*12;store8(next+offset,load8(next+offset)^1);vc_write(vc_path(output,"corrupted.bin"),next,size);return 0;
}
