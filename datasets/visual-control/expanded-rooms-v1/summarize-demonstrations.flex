// Count supervised search and return examples without exposing oracle state to
// the actor. The executed actions are recorded for correction histories.
import "../../../flex/control/dataset.flex";
import "../../../flex/control/actions.flex";

fn sd_add(counts,index) {store64(counts+index*8,load64(counts+index*8)+1);return 0;}
fn sd_direction(speed) {vc_require(f64_is_finite(speed),"nonfinite demonstration speed");if f64_gt(speed,0) {return 1;}if f64_lt(speed,0) {return -1;}return 0;}
fn sd_array(builder,counts,size) {
    pl_char(builder,91);let i=0;while i<size {if i {pl_char(builder,44);}pl_int(builder,load64(counts+i*8));i=i+1;}pl_char(builder,93);return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2,"summarize-demonstrations DATA");let data=vd_map(load64(argv+8));let bytes=vc_size;
    vc_require(bytes>=32 && vd_row_bytes(data)==56,"summary requires PVDATA03 or PVDATA04 demonstrations");let episodes=load64(data+8);let fit=load64(data+16);let length=load64(data+24);
    vc_require(episodes>=2 && episodes<=vd_episode_limit(data) && fit>=1 && fit<episodes && length>=1 && length<=512 && bytes==32+episodes*length*21224,"invalid demonstration dimensions");
    // Four groups: fitting search, fitting return, validation search, validation return.
    let supervised=alloc(32);let valid=alloc(32);let histories=alloc(32);let disagreement=alloc(32);let comparable=alloc(32);let classes=alloc(4*8*8);let expert_pairs=alloc(32);let expert_reversals=alloc(32);let executed_pairs=alloc(32);let executed_reversals=alloc(32);let episode=0;
    while episode<episodes {let base=data+32+episode*length*21224;let seen=0;let t=0;let padded=0;let previous_group= -1;let previous_expert=0;let previous_executed=0;
        while t<length {let row=base+length*21168+t*56;let phase=pb_u32(row+36);let label=pb_u32(row+40);let frame=pb_u32(row+44);
            vc_require((phase==0 || phase==0x3f800000) && (label==0 || label==0x3f800000) && (frame==0 || frame==0x3f800000) && (!label || frame) && !pb_u32(row+24),"invalid phase, mask or task feedback");
            if frame {vc_require(!padded,"valid frames after padding");let group=0;if episode>=fit {group=2;}if phase {group=group+1;}sd_add(valid,group);if group!=previous_group {previous_group=group;previous_expert=0;previous_executed=0;}
                if label {sd_add(supervised,group);seen=seen|(1<<group);let expert=ca_class(pb_read_float(row+28),pb_read_float(row+32));let executed=ca_class(pb_read_float(row+48),pb_read_float(row+52));let bucket=expert;if bucket<0 {bucket=7;}sd_add(classes,group*8+bucket);
                    if expert>=0 && executed>=0 {sd_add(comparable,group);if expert!=executed {sd_add(disagreement,group);}}
                    let e=sd_direction(pb_read_float(row+32));let x=sd_direction(pb_read_float(row+52));if e {if previous_expert {sd_add(expert_pairs,group);if e!=previous_expert {sd_add(expert_reversals,group);}}previous_expert=e;}if x {if previous_executed {sd_add(executed_pairs,group);if x!=previous_executed {sd_add(executed_reversals,group);}}previous_executed=x;}
                }else {previous_expert=0;previous_executed=0;}
            }else {padded=1;}t=t+1;
        }
        let group=0;while group<4 {if (seen>>group)&1 {sd_add(histories,group);}group=group+1;}episode=episode+1;
    }
    let out=alloc(4096);let b=alloc(32);pl_builder(b,out,4096);pl_text(b,"{\"runtime\":\"Flexscript\",\"datasetSHA256\":");pj_text(b,vc_digest(data,bytes));pl_text(b,",\"episodes\":");pl_int(b,episodes);pl_text(b,",\"fittingHistories\":");pl_int(b,fit);pl_text(b,",\"sequenceLength\":");pl_int(b,length);
    pl_text(b,",\"groupOrder\":[\"fitSearch\",\"fitReturn\",\"validationSearch\",\"validationReturn\"],\"validFrames\":");sd_array(b,valid,4);pl_text(b,",\"supervisedFrames\":");sd_array(b,supervised,4);pl_text(b,",\"historiesWithSupervision\":");sd_array(b,histories,4);pl_text(b,",\"comparableActions\":");sd_array(b,comparable,4);pl_text(b,",\"expertExecutedDisagreements\":");sd_array(b,disagreement,4);
    pl_text(b,",\"expertDirectionComparisons\":");sd_array(b,expert_pairs,4);pl_text(b,",\"expertDirectionReversals\":");sd_array(b,expert_reversals,4);pl_text(b,",\"executedDirectionComparisons\":");sd_array(b,executed_pairs,4);pl_text(b,",\"executedDirectionReversals\":");sd_array(b,executed_reversals,4);
    pl_text(b,",\"expertActionClasses\":[");let group=0;while group<4 {if group {pl_char(b,44);}sd_array(b,classes+group*8*8,8);group=group+1;}pl_text(b,"],\"classOrder\":[\"forwardLeft\",\"forwardStraight\",\"forwardRight\",\"reverseLeft\",\"reverseStraight\",\"reverseRight\",\"stop\",\"other\"]}\n");vc_require(!load64(b+24) && !pl_write(1,out,load64(b+8)),"cannot write demonstration summary");return 0;
}
