// Diagnose training labels by history without supplying privileged information
// to the actor. Class counts use the same action bins as the global summary.
import "../../../flex/control/dataset.flex";
import "../../../flex/control/actions.flex";

fn se_array(builder,counts,size) {
    pl_char(builder,91);let i=0;while i<size {if i {pl_char(builder,44);}pl_int(builder,load64(counts+i*8));i=i+1;}pl_char(builder,93);return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2,"summarize-demonstrations-by-episode DATA");let data=vd_map(load64(argv+8));let bytes=vc_size;
    vc_require(bytes>=32 && vd_row_bytes(data)==56,"summary requires PVDATA03 or PVDATA04 demonstrations");let episodes=load64(data+8);let fit=load64(data+16);let length=load64(data+24);
    vc_require(episodes>=2 && episodes<=vd_episode_limit(data) && fit>=1 && fit<episodes && length>=1 && length<=512 && bytes==32+episodes*length*21224,"invalid demonstration dimensions");
    let text=alloc(episodes*1024+2048);let b=alloc(32);pl_builder(b,text,episodes*1024+2048);pl_text(b,"{\"runtime\":\"Flexscript\",\"datasetSHA256\":");pj_text(b,vc_digest(data,bytes));pl_text(b,",\"episodes\":");pl_int(b,episodes);pl_text(b,",\"fittingHistories\":");pl_int(b,fit);pl_text(b,",\"sequenceLength\":");pl_int(b,length);pl_text(b,",\"classOrder\":[\"forwardLeft\",\"forwardStraight\",\"forwardRight\",\"reverseLeft\",\"reverseStraight\",\"reverseRight\",\"stop\",\"other\"],\"rows\":[");
    let episode=0;while episode<episodes {let counts=alloc(128);let frames=alloc(16);let disagreements=alloc(16);let base=data+32+episode*length*21224;let t=0;let padded=0;let returning=0;
        while t<length {let row=base+length*21168+t*56;let phase=pb_u32(row+36);let label=pb_u32(row+40);let frame=pb_u32(row+44);
            vc_require((phase==0 || phase==0x3f800000) && (label==0 || label==0x3f800000) && (frame==0 || frame==0x3f800000) && (!label || frame) && !pb_u32(row+24),"invalid phase, mask or task feedback");
            if frame {vc_require(!padded && (!returning || phase),"invalid padding or return transition");if phase {returning=1;}let group=0;if phase {group=1;}if label {store64(frames+group*8,load64(frames+group*8)+1);let expert=ca_class(pb_read_float(row+28),pb_read_float(row+32));let executed=ca_class(pb_read_float(row+48),pb_read_float(row+52));let bucket=expert;if bucket<0 {bucket=7;}let count=counts+(group*8+bucket)*8;store64(count,load64(count)+1);if expert>=0 && executed>=0 && expert!=executed {store64(disagreements+group*8,load64(disagreements+group*8)+1);}}}else {padded=1;}t=t+1;
        }
        if episode {pl_char(b,44);}pl_text(b,"{\"index\":");pl_int(b,episode);pl_text(b,",\"fit\":");pj_bool_text(b,episode<fit);pl_text(b,",\"supervisedFrames\":");se_array(b,frames,2);pl_text(b,",\"expertExecutedDisagreements\":");se_array(b,disagreements,2);pl_text(b,",\"searchClasses\":");se_array(b,counts,8);pl_text(b,",\"returnClasses\":");se_array(b,counts+64,8);pl_char(b,125);
        syscall(11,counts,128,0,0,0,0);syscall(11,frames,16,0,0,0,0);syscall(11,disagreements,16,0,0,0,0);episode=episode+1;
    }pl_text(b,"]}\n");vc_require(!load64(b+24) && !pl_write(1,text,load64(b+8)),"cannot write episode summary");return 0;
}
