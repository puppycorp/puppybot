// Seeded scene catalog. Layouts 6/7 are excluded from all fitting histories.
import "../../../flex/control/scene.flex";
fn ds_environment(path,layout,hx,hy) {
    vc_boxes=alloc(32*128);vc_box_count=0;
    vc_box("Floor",0,0,vc_number(-16,1000),hx,hy,vc_number(16,1000),vc_number(55+layout,100),vc_number(43,100),vc_number(29,100),0,0);
    vc_wall("Wall.west",pb_neg(hx),0,vc_number(6,100),hy);vc_wall("Wall.east",hx,0,vc_number(6,100),hy);
    vc_wall("Wall.south",0,pb_neg(hy),hx,vc_number(6,100));vc_wall("Wall.north",0,hy,hx,vc_number(6,100));
    if layout%2 {let group=layout/2;let px=vc_number(100+group*10,100);let centre=vc_number(-20+group*12,100);let half=vc_number(60+group*3,100);let low=f64_sub(centre,half);let high=f64_add(centre,half);
        vc_wall("Wall.partition-a",px,f64_mul(f64_sub(low,hy),vc_number(1,2)),vc_number(6,100),f64_mul(f64_add(low,hy),vc_number(1,2)));
        vc_wall("Wall.partition-b",px,f64_mul(f64_add(high,hy),vc_number(1,2)),vc_number(6,100),f64_mul(f64_sub(hy,high),vc_number(1,2)));
    }
    let count=vc_box_count-1;let vertices=vc_box_count*36;let bytes=256+count*128+vertices*72;let data=alloc(bytes);pb_zero(data,bytes);
    vc_copy(data,"PBENV001",8);store64(data+8,count);store64(data+16,vertices);store64(data+24,vertices);store64(data+64,pb_neg(hx));store64(data+72,pb_neg(hy));store64(data+80,hx);store64(data+88,hy);
    store64(data+96,vc_number((layout%3-1)*4,100));store64(data+104,vc_number(((layout*2)%3-1)*4,100));store64(data+112,vc_number((layout-3)*35,1000));
    let name=vc_concat("Approach35 layout ",vc_int(layout));vc_copy(data+128,name,pl_size(name));let full=data+256+count*128;let overview=full+vertices*36;let i=0;
    while i<vc_box_count {let record=vc_boxes+i*128;if i {vc_copy(data+256+(i-1)*128,record,96);}vc_mesh_box(record,full+i*36*36,overview+i*36*36);i=i+1;}
    vc_write(path,data,bytes);syscall(11,data,bytes,0,0,0,0);syscall(11,vc_boxes,32*128,0,0,0,0);return 0;
}
fn ds_layout(path,layout,hx,hy) {
    let text=alloc(4096);let b=alloc(32);pl_builder(b,text,4096);pl_text(b,"{\"layoutId\":");pl_int(b,layout);pl_text(b,",\"fit\":");pj_bool_text(b,layout<6);pl_text(b,",\"startRoom\":0,\"rooms\":[[");pl_float(b,pb_neg(hx));pl_text(b,",");pl_float(b,pb_neg(hy));pl_text(b,",");let edge=hx;if layout%2 {edge=vc_number(100+(layout/2)*10,100);}pl_float(b,edge);pl_text(b,",");pl_float(b,hy);pl_text(b,"]");
    if layout%2 {pl_text(b,",[");pl_float(b,edge);pl_text(b,",");pl_float(b,pb_neg(hy));pl_text(b,",");pl_float(b,hx);pl_text(b,",");pl_float(b,hy);pl_text(b,"]");}pl_text(b,"]}\n");vc_require(!load64(b+24),"layout metadata overflow");vc_write(path,text,load64(b+8));return 0;
}
fn ds_case(path,layout,index,hx,hy) {
    let seed=8800000+layout*100+index;vc_case(path,"flex/sim/cases/find-return-house.json",seed,layout%2);let root=vc_json_file(path);let object=pj_index(pj_get(root,"objects"),0);let position=pj_get(object,"position");let xmin=vc_number(18,10);if layout%2 {xmin=vc_number(185+(layout/2)*10,100);}
    vc_set_number(pj_index(position,0),vc_uniform(xmin,f64_sub(hx,vc_number(65,100))));let ymin=vc_number(-9,10);let ymax=vc_number(9,10);if layout%2 {ymin=vc_number(115,100);ymax=f64_sub(hy,vc_number(65,100));}vc_set_number(pj_index(position,1),vc_uniform(ymin,ymax));
    let color=pj_get(object,"color");let r=95;let g=22;let blue=22;let hue=index%6;if hue==1 {r=20;g=45;blue=95;}if hue==2 {r=100;g=82;blue=18;}if hue==3 {r=24;g=85;blue=38;}if hue==4 {r=68;g=28;blue=88;}if hue==5 {r=100;g=49;blue=12;}
    vc_set_number(pj_index(color,0),f64_from_i64(r));vc_set_number(pj_index(color,1),f64_from_i64(g));vc_set_number(pj_index(color,2),f64_from_i64(blue));let size=pj_get(object,"halfSize");vc_set_number(pj_index(size,0),vc_number(18+(index%5)*2,1000));vc_set_number(pj_index(size,1),vc_number(12+(index%3)*2,1000));vc_set_number(pj_get(object,"yawDegrees"),f64_from_i64(-60+(index*17+layout*11)%121));
    let text=alloc(16384);let b=alloc(32);pl_builder(b,text,16384);pj_emit(b,root);pl_char(b,10);vc_require(!pj_error && !load64(b+24),"case metadata overflow");vc_write(path,text,load64(b+8));return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2,"generate NEW_OUTPUT");let output=vc_absolute(load64(argv+8));vc_mkdir(output);let layout=0;
    while layout<8 {let root=vc_path(output,vc_int(layout));vc_mkdir(root);let hx=vc_number(310+(layout%6)*16+(layout/6)*19,100);let hy=vc_number(260+((layout*3)%7)*10,100);let environment=vc_path(root,"environment.bin");let metadata=vc_path(root,"layout.json");ds_environment(environment,layout,hx,hy);ds_layout(metadata,layout,hx,hy);let i=0;
        while i<16 {let scene=vc_path(root,vc_int(i));vc_mkdir(scene);ds_case(vc_path(scene,"case.json"),layout,i,hx,hy);vc_require(!syscall(88,environment,vc_path(scene,"environment.bin"),0,0,0,0) && !syscall(88,metadata,vc_path(scene,"layout.json"),0,0,0,0),"cannot link layout files");i=i+1;}layout=layout+1;
    }pl_print(1,"Generated 128 strict-task scenes with disjoint fitting/validation layouts.\n");return 0;
}
