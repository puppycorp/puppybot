// Compare supervised initial labels only when the actor's complete initial
// input is identical. All episodes start with zero recurrent state.
import "../../../flex/control/dataset.flex";
import "../../../flex/control/actions.flex";
import "../../../flex/control/augmentation.flex";

fn sa_same(memcmp,a,b) {return !ffi_call(memcmp,a,b,21168,0,0,0) && !ffi_call(memcmp,a+21168,b+21168,28,0,0,0);}
fn sa_counts(builder,counts) {pl_char(builder,91);let i=0;while i<7 {if i {pl_char(builder,44);}pl_int(builder,load64(counts+i*8));i=i+1;}pl_char(builder,93);return 0;}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2 || (argc==3 && pl_equal(load64(argv+16),"--neutral-drive")),"summarize-initial-label-ambiguity DATA [--neutral-drive]");let neutral=argc==3;let data=vd_map(load64(argv+8));let bytes=vc_size;
    vc_require(bytes>=32 && vd_row_bytes(data)==56,"summary requires PVDATA03 or PVDATA04 demonstrations");let episodes=load64(data+8);let fit=load64(data+16);let length=load64(data+24);
    vc_require(episodes>=2 && episodes<=vd_episode_limit(data) && fit>=1 && fit<episodes && length>=1 && length<=512 && bytes==32+episodes*length*21224,"invalid demonstration dimensions");
    let cmp=ffi_symbol(ffi_open("libc.so.6"),"memcmp");vc_require(cmp,"memcmp unavailable");let records=alloc(episodes*32);pb_zero(records,episodes*32);let inputs=alloc(episodes*21196);let counts=alloc(episodes*2*7*8);pb_zero(counts,episodes*2*7*8);let episode_group=alloc(episodes*8);let episode_action=alloc(episodes*8);let groups=0;let supervised=0;let i=0;
    while i<episodes {let base=data+32+i*length*21224;let row=base+length*21168;let label=pb_u32(row+40);let valid=pb_u32(row+44);
        vc_require((label==0 || label==0x3f800000) && (valid==0 || valid==0x3f800000) && (!label || valid) && !pb_u32(row+24),"invalid initial masks or task feedback");
        store64(episode_group+i*8,-1);if label {let action=ca_class(pb_read_float(row+28),pb_read_float(row+32));vc_require(action>=0,"initial label outside joint action codec");let input=inputs+i*21196;vc_copy(input,base,21168);vc_copy(input+21168,row,28);if neutral {pf_neutral_drive(input+21168);}let digest=vc_digest(input,21196);let group=0;
            let matched=0;while group<groups && !matched {let representative=load64(records+group*32);if pl_equal(digest,load64(records+group*32+8)) && sa_same(cmp,input,representative) {matched=1;}else {group=group+1;}}
            if group==groups {store64(records+group*32,input);store64(records+group*32+8,digest);groups=groups+1;}
            let split=0;if i>=fit {split=1;}let slot=counts+(group*14+split*7+action)*8;store64(slot,load64(slot)+1);store64(episode_group+i*8,group);store64(episode_action+i*8,action);supervised=supervised+1;
        }i=i+1;
    }
    let conflicting=0;let lower_fit=0;let lower_validation=0;let group=0;
    while group<groups {let split=0;let any=0;while split<2 {let sum=0;let max=0;let distinct=0;let action=0;while action<7 {let n=load64(counts+(group*14+split*7+action)*8);sum=sum+n;if n>max {max=n;}if n {distinct=distinct+1;}action=action+1;}if distinct>1 {any=1;}if split {lower_validation=lower_validation+sum-max;}else {lower_fit=lower_fit+sum-max;}split=split+1;}if any {conflicting=conflicting+1;}group=group+1;}
    let capacity=65536+episodes*400;let out=alloc(capacity);let b=alloc(32);pl_builder(b,out,capacity);pl_text(b,"{\"passed\":true,\"runtime\":\"Flexscript\",\"dataSHA256\":");pj_text(b,vc_digest(data,bytes));pl_text(b,",\"driveFeedbackNeutralized\":");pj_bool_text(b,neutral);pl_text(b,",\"episodes\":");pl_int(b,episodes);pl_text(b,",\"fittingHistories\":");pl_int(b,fit);pl_text(b,",\"supervisedInitialFrames\":");pl_int(b,supervised);pl_text(b,",\"distinctInitialInputs\":");pl_int(b,groups);pl_text(b,",\"conflictingInputsWithinSplit\":");pl_int(b,conflicting);pl_text(b,",\"minimumInitialClassificationErrors\":[");pl_int(b,lower_fit);pl_char(b,44);pl_int(b,lower_validation);pl_text(b,"],\"splitOrder\":[\"fit\",\"validation\"],\"actionClassOrder\":[\"forwardLeft\",\"forwardStraight\",\"forwardRight\",\"reverseLeft\",\"reverseStraight\",\"reverseRight\",\"stop\"],\"initialMemoryZero\":true,\"actorInputsUnchanged\":true,\"offlineAnalysisOnly\":true,\"conflicts\":[");
    group=0;let printed=0;while group<groups {let split=0;let any=0;while split<2 {let distinct=0;let action=0;while action<7 {if load64(counts+(group*14+split*7+action)*8) {distinct=distinct+1;}action=action+1;}if distinct>1 {any=1;}split=split+1;}
        if any {if printed {pl_char(b,44);}printed=printed+1;pl_text(b,"{\"inputSHA256\":");pj_text(b,load64(records+group*32+8));pl_text(b,",\"fit\":");sa_counts(b,counts+group*14*8);pl_text(b,",\"validation\":");sa_counts(b,counts+(group*14+7)*8);pl_text(b,",\"examples\":[");i=0;let examples=0;while i<episodes {if load64(episode_group+i*8)==group {if examples {pl_char(b,44);}examples=examples+1;pl_text(b,"{\"episode\":");pl_int(b,i);pl_text(b,",\"split\":");if i<fit {pj_text(b,"fit");}else {pj_text(b,"validation");}pl_text(b,",\"actionClass\":");pl_int(b,load64(episode_action+i*8));pl_char(b,125);}i=i+1;}pl_text(b,"]}");}group=group+1;
    }pl_text(b,"]}\n");vc_require(!load64(b+24) && !pl_write(1,out,load64(b+8)),"cannot write initial label summary");return 0;
}
