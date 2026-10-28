// Count conflicting labels for byte-identical complete actor observation
// prefixes. Parent nodes encode earlier inputs; collisions are checked by bytes.
import "../../../flex/control/dataset.flex";
import "../../../flex/control/actions.flex";
import "../../../flex/control/augmentation.flex";

global sp_nodes=0;
global sp_buckets=0;
global sp_count=0;
global sp_capacity=0;
global sp_digest=0;
global sp_frame=0;
global sp_compare=0;
global sp_neutral=0;

fn sp_same(node,parent,image,row) {
    if load64(node)!=parent || ffi_call(sp_compare,node+32,sp_digest,32,0,0,0) || ffi_call(sp_compare,load64(node+8),image,21168,0,0,0) {return 0;}
    if sp_neutral {return !ffi_call(sp_compare,load64(node+16)+20,row+20,8,0,0,0);}
    return !ffi_call(sp_compare,load64(node+16),row,28,0,0,0);
}
fn sp_node(parent,image,row,time) {
    vc_copy(sp_frame,image,21168);vc_copy(sp_frame+21168,row,28);if sp_neutral {pf_neutral_drive(sp_frame+21168);}
    ffi_call(vc_sha,sp_frame,21196,sp_digest,0,0,0);let bucket=(pb_u32(sp_digest)^(parent*16777619))&(sp_capacity-1);let id=load64(sp_buckets+bucket*8);
    while id {let node=sp_nodes+(id-1)*192;if sp_same(node,parent,image,row) {return id;}bucket=(bucket+1)&(sp_capacity-1);id=load64(sp_buckets+bucket*8);}
    sp_count=sp_count+1;id=sp_count;let node=sp_nodes+(id-1)*192;store64(node,parent);store64(node+8,image);store64(node+16,row);store64(node+24,time);vc_copy(node+32,sp_digest,32);store64(sp_buckets+bucket*8,id);return id;
}
fn sp_counts(b,node,split) {pl_char(b,91);let i=0;while i<7 {if i {pl_char(b,44);}pl_int(b,load64(node+64+(split*7+i)*8));i=i+1;}return pl_char(b,93);}
fn sp_disagreement(node,split) {
    let total=0;let largest=0;let i=0;while i<7 {let count=load64(node+64+(split*7+i)*8);total=total+count;largest=pb_max(largest,count);i=i+1;}return total-largest;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2 || (argc==3 && pl_equal(load64(argv+16),"--neutral-drive")),"summarize-prefix-label-ambiguity DATA [--neutral-drive]");sp_neutral=argc==3;
    let data=vd_map(load64(argv+8));let bytes=vc_size;vc_require(bytes>=32 && vd_row_bytes(data)==56,"summary requires PVDATA03 or PVDATA04 demonstrations");
    let episodes=load64(data+8);let fit=load64(data+16);let length=load64(data+24);vc_require(episodes>=2 && episodes<=vd_episode_limit(data) && fit>=1 && fit<episodes && length>=1 && length<=512 && bytes==32+episodes*length*21224,"invalid demonstration dimensions");
    let maximum=episodes*length;sp_nodes=alloc(maximum*192);pb_zero(sp_nodes,maximum*192);sp_capacity=1;while sp_capacity<maximum*2 {sp_capacity=sp_capacity*2;}sp_buckets=alloc(sp_capacity*8);pb_zero(sp_buckets,sp_capacity*8);
    sp_digest=alloc(32);sp_frame=alloc(21196);sp_compare=ffi_symbol(ffi_open("libc.so.6"),"memcmp");vc_sha=ffi_symbol(ffi_open("libcrypto.so.3"),"SHA256");vc_require(sp_compare && vc_sha,"hash or comparison unavailable");
    let members=alloc(maximum*8);pb_zero(members,maximum*8);let supervised_fit=0;let supervised_val=0;let valid_frames=0;let episode=0;
    while episode<episodes {
        let base=data+32+episode*length*21224;let parent=0;let time=0;let padded=0;let split=0;if episode>=fit {split=1;}
        while time<length {
            let row=base+length*21168+time*56;let valid=pb_u32(row+44);let label=pb_u32(row+40);let phase=pb_u32(row+36);
            vc_require((valid==0 || valid==0x3f800000) && (label==0 || label==0x3f800000) && (phase==0 || phase==0x3f800000) && (!label || valid) && !pb_u32(row+24),"invalid observation masks or task feedback");
            if valid {vc_require(!padded,"valid observation follows padding");let field=0;while field<7 {vc_require(f64_is_finite(pb_read_float(row+field*4)),"nonfinite observation feedback");field=field+1;}let image=base+time*21168;parent=sp_node(parent,image,row,time);valid_frames=valid_frames+1;
                if label {let action=ca_class(pb_read_float(row+28),pb_read_float(row+32));vc_require(action>=0,"label outside joint action codec");let node=sp_nodes+(parent-1)*192;let count=node+64+(split*7+action)*8;store64(count,load64(count)+1);let phases=node+176+split*8;let bit=1;if phase {bit=2;}store64(phases,load64(phases)|bit);store64(members+(episode*length+time)*8,parent);if split {supervised_val=supervised_val+1;}else {supervised_fit=supervised_fit+1;}}
            }else {padded=1;}time=time+1;
        }episode=episode+1;
    }
    let conflicts=0;let fit_errors=0;let val_errors=0;let first_fit=0;let first_val=0;let phase_conflicts=0;let bins=alloc(96);let phases=alloc(48);pb_zero(bins,96);pb_zero(phases,48);let id=1;
    while id<=sp_count {let node=sp_nodes+(id-1)*192;let a=sp_disagreement(node,0);let b=sp_disagreement(node,1);if a || b {conflicts=conflicts+1;if (a && load64(node+176)==3) || (b && load64(node+184)==3) {phase_conflicts=phase_conflicts+1;}let time=load64(node+24);if !time {first_fit=first_fit+a;first_val=first_val+b;}let bin=5;if !time {bin=0;}else if time<5 {bin=1;}else if time<10 {bin=2;}else if time<25 {bin=3;}else if time<50 {bin=4;}let slot=bins+bin*16;store64(slot,load64(slot)+a);store64(slot+8,load64(slot+8)+b);
        let split=0;while split<2 {let errors=a;if split {errors=b;}let mask=load64(node+176+split*8);if errors {vc_require(mask>=1 && mask<=3,"missing phase on a supervised prefix");let p=phases+(mask-1)*16+split*8;store64(p,load64(p)+errors);}split=split+1;}}
        fit_errors=fit_errors+a;val_errors=val_errors+b;id=id+1;}
    let out=alloc(4194304);let b=alloc(32);pl_builder(b,out,4194304);pl_text(b,"{\"passed\":true,\"runtime\":\"Flexscript\",\"dataSHA256\":");pj_text(b,vc_digest(data,bytes));
    pl_text(b,",\"driveFeedbackNeutralized\":");pj_bool_text(b,sp_neutral);pl_text(b,",\"episodes\":");pl_int(b,episodes);pl_text(b,",\"fittingHistories\":");pl_int(b,fit);pl_text(b,",\"sequenceLength\":");pl_int(b,length);pl_text(b,",\"validFrames\":");pl_int(b,valid_frames);
    pl_text(b,",\"supervisedFrames\":[");pl_int(b,supervised_fit);pl_char(b,44);pl_int(b,supervised_val);pl_text(b,"],\"distinctObservationPrefixes\":");pl_int(b,sp_count);pl_text(b,",\"conflictingPrefixesWithinSplit\":");pl_int(b,conflicts);pl_text(b,",\"conflictingPrefixesWithMixedPhase\":");pl_int(b,phase_conflicts);
    pl_text(b,",\"minimumClassificationErrors\":[");pl_int(b,fit_errors);pl_char(b,44);pl_int(b,val_errors);pl_text(b,"],\"initialFrameErrors\":[");pl_int(b,first_fit);pl_char(b,44);pl_int(b,first_val);pl_text(b,"],\"laterFrameErrors\":[");pl_int(b,fit_errors-first_fit);pl_char(b,44);pl_int(b,val_errors-first_val);
    pl_text(b,"],\"errorByTime\":[");let bin=0;while bin<6 {if bin {pl_char(b,44);}pl_char(b,91);pl_int(b,load64(bins+bin*16));pl_char(b,44);pl_int(b,load64(bins+bin*16+8));pl_char(b,93);bin=bin+1;}pl_text(b,"],\"timeBinOrder\":[\"0\",\"1-4\",\"5-9\",\"10-24\",\"25-49\",\"50+\"],\"errorByPhase\":[");bin=0;while bin<3 {if bin {pl_char(b,44);}pl_char(b,91);pl_int(b,load64(phases+bin*16));pl_char(b,44);pl_int(b,load64(phases+bin*16+8));pl_char(b,93);bin=bin+1;}pl_text(b,"],\"phaseOrder\":[\"search\",\"return\",\"mixed\"],\"initialMemoryZero\":true,\"prefixBytesIndependentlyCompared\":true,\"actorInputsUnchanged\":true,\"offlineAnalysisOnly\":true,\"notEpisodeSuccessEstimate\":true,\"conflicts\":[");id=1;let printed=0;
    while id<=sp_count && printed<32 {let node=sp_nodes+(id-1)*192;if sp_disagreement(node,0) || sp_disagreement(node,1) {
        if printed {pl_char(b,44);}printed=printed+1;pl_text(b,"{\"prefixId\":");pl_int(b,id);pl_text(b,",\"time\":");pl_int(b,load64(node+24));pl_text(b,",\"fit\":");sp_counts(b,node,0);pl_text(b,",\"validation\":");sp_counts(b,node,1);pl_text(b,",\"phaseMasks\":[");pl_int(b,load64(node+176));pl_char(b,44);pl_int(b,load64(node+184));pl_text(b,"],\"examples\":[");let position=0;let example=0;
        while position<maximum {if load64(members+position*8)==id {if example {pl_char(b,44);}example=example+1;let e=position/length;let t=position%length;let row=data+32+e*length*21224+length*21168+t*56;pl_text(b,"{\"episode\":");pl_int(b,e);pl_text(b,",\"time\":");pl_int(b,t);pl_text(b,",\"actionClass\":");pl_int(b,ca_class(pb_read_float(row+28),pb_read_float(row+32)));pl_char(b,125);}position=position+1;}pl_text(b,"]}");}id=id+1;}
    pl_text(b,"],\"conflictExamplesTruncated\":");pj_bool_text(b,printed<conflicts);pl_text(b,"}\n");vc_require(!load64(b+24) && !pl_write(1,out,load64(b+8)),"cannot write prefix summary");return 0;
}
