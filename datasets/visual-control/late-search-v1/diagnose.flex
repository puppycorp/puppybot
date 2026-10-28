// Compare oracle targets with actual student commands in two temporal windows.
import "../../../flex/control/dataset.flex";
import "../../../flex/control/actions.flex";
fn ls_counts(b,counts) {
    pl_char(b,91);let i=0;while i<7 {if i {pl_char(b,44);}pl_int(b,load64(counts+i*8));i=i+1;}pl_char(b,93);return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"diagnose DATA OUTPUT_JSON");let data=vc_map(load64(argv+8));let bytes=vc_size;let n=load64(data+8);let fit=load64(data+16);let length=load64(data+24);
    vc_require(vd_row_bytes(data)==56 && n>=2 && n<=64 && fit>=1 && fit<n && length>=120 && length<=512 && bytes==32+n*length*21224,"invalid later-search dataset");
    let text=alloc(n*4096);let b=alloc(32);pl_builder(b,text,n*4096);pl_text(b,"{\"dataSHA256\":");pj_text(b,vc_digest(data,bytes));pl_text(b,",\"classes\":[\"forward-left\",\"forward\",\"forward-right\",\"reverse-left\",\"reverse\",\"reverse-right\",\"stop\"],\"windows\":[");let episode=0;
    while episode<n {let base=data+32+episode*length*21224;let stage=0;while stage<2 {let targets=alloc(56);let actual=alloc(56);let frames=0;let disagreements=0;let speed_disagreements=0;let contacts=0;let forward_contacts=0;let reverse_contacts=0;let returning=0;let t=stage*60;
            while t<(stage+1)*60 {let row=base+length*21168+t*56;if pb_u32(row+44) && pb_u32(row+40) {let target=ca_class(pb_read_float(row+28),pb_read_float(row+32));let executed=ca_class(pb_read_float(row+48),pb_read_float(row+52));vc_require(target>=0 && executed>=0,"unsupported categorical action");let p=targets+target*8;store64(p,load64(p)+1);p=actual+executed*8;store64(p,load64(p)+1);frames=frames+1;disagreements=disagreements+(target!=executed);speed_disagreements=speed_disagreements+(pb_u32(row+32)!=pb_u32(row+52));returning=returning+(pb_u32(row+36)!=0);
                    if pb_u32(row+20) {contacts=contacts+1;forward_contacts=forward_contacts+f64_gt(pb_read_float(row+4),0);reverse_contacts=reverse_contacts+f64_lt(pb_read_float(row+4),0);}
                }t=t+1;}
            if episode || stage {pl_char(b,44);}pl_text(b,"{\"episode\":");pl_int(b,episode);pl_text(b,",\"fit\":");pj_bool_text(b,episode<fit);pl_text(b,",\"firstAction\":");pl_int(b,stage*60);pl_text(b,",\"frames\":");pl_int(b,frames);pl_text(b,",\"oracleDisagreements\":");pl_int(b,disagreements);pl_text(b,",\"speedDisagreements\":");pl_int(b,speed_disagreements);pl_text(b,",\"contactFrames\":");pl_int(b,contacts);pl_text(b,",\"forwardContactFrames\":");pl_int(b,forward_contacts);pl_text(b,",\"reverseContactFrames\":");pl_int(b,reverse_contacts);pl_text(b,",\"returningFrames\":");pl_int(b,returning);pl_text(b,",\"oracleCounts\":");ls_counts(b,targets);pl_text(b,",\"executedCounts\":");ls_counts(b,actual);pl_char(b,125);stage=stage+1;
        }episode=episode+1;
    }pl_text(b,"]}\n");vc_require(!load64(b+24),"later-search diagnostic exceeded capacity");vc_write(load64(argv+16),text,load64(b+8));return 0;
}
