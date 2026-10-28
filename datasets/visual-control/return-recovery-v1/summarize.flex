// Inspect native data balance without changing labels, split roles or history.
import "../../../flex/control/training.flex";
import "../../../flex/control/dataset.flex";
import "../../../flex/control/actions.flex";
fn rs_counts(b,values,weighted) {
    let phase=0;pl_char(b,91);while phase<2 {if phase {pl_char(b,44);}pl_char(b,91);let k=0;while k<7 {if k {pl_char(b,44);}if weighted {pl_float(b,load64(values+(phase*7+k)*8));}else {pl_int(b,load64(values+(phase*7+k)*8));}k=k+1;}pl_char(b,93);phase=phase+1;}pl_char(b,93);return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"summarize DATA OUTPUT_JSON");let data=vc_map(load64(argv+8));let bytes=vc_size;let n=load64(data+8);let fit=load64(data+16);let t=load64(data+24);vc_require(vd_row_bytes(data)==56 && n>=2 && n<=256 && fit>=1 && fit<n && t>=1 && t<=512 && bytes==32+n*t*21224,"invalid dense dataset");
    let counts=alloc(2*14*8);let weights=alloc(2*14*8);let totals=alloc(2*32);let episode=0;
    while episode<n {let split=episode>=fit;let base=data+32+episode*t*21224;let row=0;while row<t {let values=base+t*21168+row*56;let valid=pb_read_float(values+44);let mask=pb_read_float(values+40);if f64_gt(valid,0) {let p=totals+split*32;store64(p,load64(p)+1);if pb_u32(values+20) {store64(p+8,load64(p+8)+1);}if load64(values+28)!=load64(values+48) {store64(p+16,load64(p+16)+1);}
                if f64_gt(mask,0) {let k=ca_class(pb_read_float(values+28),pb_read_float(values+32));vc_require(k>=0,"unsupported categorical target");let phase=pb_u32(values+36)!=0;let offset=(split*14+phase*7+k)*8;store64(counts+offset,load64(counts+offset)+1);store64(weights+offset,f64_add(load64(weights+offset),pt_control_weight(mask,pb_read_float(values+32),pb_read_float(values+4))));store64(p+24,load64(p+24)+1);}
            }row=row+1;}episode=episode+1;
    }
    let text=alloc(8192);let b=alloc(32);pl_builder(b,text,8192);pl_text(b,"{\"episodes\":");pl_int(b,n);pl_text(b,",\"fitEpisodes\":");pl_int(b,fit);pl_text(b,",\"sequenceLength\":");pl_int(b,t);pl_text(b,",\"dataSHA256\":");pj_text(b,vc_digest(data,bytes));pl_text(b,",\"classOrder\":[\"forward-left\",\"forward\",\"forward-right\",\"reverse-left\",\"reverse\",\"reverse-right\",\"stop\"],\"phaseOrder\":[\"search\",\"return\"],\"splits\":[");let split=0;
    while split<2 {if split {pl_char(b,44);}let p=totals+split*32;pl_text(b,"{\"fit\":");pj_bool_text(b,!split);pl_text(b,",\"validFrames\":");pl_int(b,load64(p));pl_text(b,",\"contactFrames\":");pl_int(b,load64(p+8));pl_text(b,",\"oracleDisagreesWithExecuted\":");pl_int(b,load64(p+16));pl_text(b,",\"supervisedFrames\":");pl_int(b,load64(p+24));pl_text(b,",\"targetCounts\":");rs_counts(b,counts+split*14*8,0);pl_text(b,",\"effectiveControlWeights\":");rs_counts(b,weights+split*14*8,1);pl_char(b,125);split=split+1;}
    pl_text(b,"]}\n");vc_require(!load64(b+24),"summary overflow");vc_write(load64(argv+16),text,load64(b+8));return 0;
}
