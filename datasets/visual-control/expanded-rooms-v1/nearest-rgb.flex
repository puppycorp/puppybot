// Compare one recorded actor image with fitting frames only. Pixel distance is
// a diagnostic of raw visual similarity, not semantic recognition or success.
import "../../../flex/control/dataset.flex";
import "../../../flex/control/actions.flex";
fn nr_insert(records,distance,episode,step,row,feedback) {
    let i=4;while i>0 && distance<load64(records+(i-1)*40) {let j=0;while j<5 {store64(records+i*40+j*8,load64(records+(i-1)*40+j*8));j=j+1;}i=i-1;}
    let record=records+i*40;store64(record,distance);store64(record+8,episode);store64(record+16,step);store64(record+24,row);store64(record+32,feedback);return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==5,"nearest-rgb DATA QUERY_RGB QUERY_FEEDBACK OUTPUT");let data=vc_map(vc_absolute(load64(argv+8)));let bytes=vc_size;let n=load64(data+8);let fit=load64(data+16);let length=load64(data+24);vc_require(vd_row_bytes(data)==56 && n>=2 && n<=256 && fit>=1 && fit<n && length>=1 && length<=512 && bytes==32+n*length*21224,"invalid nearest-frame dataset");
    let rgb=vc_map(vc_absolute(load64(argv+16)));vc_require(vc_size==21168,"invalid query RGB");let own=vc_map(vc_absolute(load64(argv+24)));vc_require(vc_size==28 && !pb_u32(own+24),"invalid query feedback");let best=alloc(2*5*40);let i=0;while i<10 {store64(best+i*40,0x7fffffffffffffff);i=i+1;}let counts=alloc(16);let episode=0;
    while episode<fit {let base=data+32+episode*length*21224;let t=0;while t<length {let row=base+length*21168+t*56;if vd_valid_word(row,56) && pb_u32(row+40) {let phase=pb_u32(row+36)!=0;let records=best+phase*5*40;store64(counts+phase*8,load64(counts+phase*8)+1);let image=base+t*21168;let sum=0;let p=0;let limit=load64(records+4*40);while p<21168 && sum<=limit {let delta=load8(image+p)-load8(rgb+p);if delta<0 {delta= -delta;}sum=sum+delta;p=p+1;}
            if p==21168 && sum<limit {let feedback=0;let field=0;while field<7 {feedback=f64_add(feedback,f64_magnitude(f64_sub(pb_read_float(row+field*4),pb_read_float(own+field*4))));field=field+1;}nr_insert(records,sum,episode,t,row,feedback);}}
        t=t+1;}episode=episode+1;}
    let text=alloc(8192);let b=alloc(32);pl_builder(b,text,8192);pl_text(b,"{\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"sourceDataSHA256\":");pj_text(b,vc_digest(data,bytes));pl_text(b,",\"queryRGBSHA256\":");pj_text(b,vc_digest(rgb,21168));pl_text(b,",\"queryFeedbackSHA256\":");pj_text(b,vc_digest(own,28));pl_text(b,",\"metric\":\"Raw 84x84 RGB mean absolute difference; no recurrent state or semantic matching\",\"validationFramesExcluded\":true,\"phases\":[");let phase=0;
    while phase<2 {if phase {pl_char(b,44);}pl_text(b,"{\"phase\":");if phase {pj_text(b,"return");}else {pj_text(b,"search");}pl_text(b,",\"framesCompared\":");pl_int(b,load64(counts+phase*8));pl_text(b,",\"nearest\":[");let k=0;while k<5 {let record=best+phase*5*40+k*40;vc_require(load64(record)!=0x7fffffffffffffff,"not enough fitting frames in phase");if k {pl_char(b,44);}let row=load64(record+24);pl_text(b,"{\"episode\":");pl_int(b,load64(record+8));pl_text(b,",\"actionIndex\":");pl_int(b,load64(record+16));pl_text(b,",\"meanAbsoluteRGB\":");pl_float(b,f64_div(f64_from_i64(load64(record)),f64_from_i64(21168*255)));pl_text(b,",\"feedbackL1\":");pl_float(b,load64(record+32));pl_text(b,",\"actionClass\":");pl_int(b,ca_class(pb_read_float(row+28),pb_read_float(row+32)));pl_char(b,125);k=k+1;}pl_text(b,"]}");phase=phase+1;}
    pl_text(b,"]}\n");vc_require(!load64(b+24),"nearest-frame output overflow");vc_write(vc_absolute(load64(argv+32)),text,load64(b+8));return 0;
}
