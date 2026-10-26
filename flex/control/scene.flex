// Seeded direct-control curriculum and a two-room hidden-target challenge.
// The world file is simulator input only; the actor receives no layout fields.
import "host.flex";
global vc_boxes=0;
global vc_box_count=0;
fn vc_box(name,x,y,z,hx,hy,hz,r,g,b,collision,cutaway) {
    let record=vc_boxes+vc_box_count*128;vc_box_count=vc_box_count+1;vc_require(vc_box_count<=32,"too many curriculum solids");
    vc_copy(record,name,pl_size(name));store64(record+48,x);store64(record+56,y);store64(record+64,z);
    store64(record+72,hx);store64(record+80,hy);store64(record+88,hz);store64(record+104,r);store64(record+112,g);store64(record+120,b);
    store64(record+96,collision+cutaway*2);return record;
}
fn vc_wall(name,x,y,hx,hy) {return vc_box(name,x,y,vc_number(125,100),hx,hy,vc_number(125,100),vc_number(76,100),vc_number(74,100),vc_number(68,100),1,1);}
fn vc_mesh_box(record,full,overview) {
    // Face corners and normals match the simulator's outward-wound box mesh.
    let faces="046213750154267302314576";let face=0;
    while face<6 {let normal=alloc(24);let axis=face/2;let sign=-1;if face&1 {sign=1;}store64(normal+axis*8,f64_from_i64(sign));let j=0;
        while j<6 {let corner=j;if j>=3 {corner=j-2;}if j==3 {corner=0;}let index=load8(faces+face*4+corner)-48;let at=(face*6+j)*36;let k=0;
            while k<3 {let direction=-1;if index&(1<<k) {direction=1;}let value=f64_add(load64(record+48+k*8),f64_mul(load64(record+72+k*8),f64_from_i64(direction)));
                pb_put32(full+at+k*4,pb_f64_to_f32(value));if k==2 && load64(record+96)&2 {value=pb_fmin(value,vc_number(38,100));}
                pb_put32(overview+at+k*4,pb_f64_to_f32(value));let n=pb_f64_to_f32(load64(normal+k*8));pb_put32(full+at+12+k*4,n);pb_put32(overview+at+12+k*4,n);
                let color=pb_f64_to_f32(load64(record+104+k*8));pb_put32(full+at+24+k*4,color);pb_put32(overview+at+24+k*4,color);k=k+1;}j=j+1;}
        syscall(11,normal,24,0,0,0,0);face=face+1;}return 0;
}
fn vc_environment(path,hidden) {
    vc_boxes=alloc(32*128);vc_box_count=0;
    vc_box("Floor",0,0,vc_number(-16,1000),vc_number(35,10),f64_from_i64(3),vc_number(16,1000),vc_number(58,100),vc_number(43,100),vc_number(29,100),0,0);
    vc_wall("Wall.west",vc_number(-35,10),0,vc_number(6,100),f64_from_i64(3));vc_wall("Wall.east",vc_number(35,10),0,vc_number(6,100),f64_from_i64(3));
    vc_wall("Wall.south",0,f64_from_i64(-3),vc_number(35,10),vc_number(6,100));vc_wall("Wall.north",0,f64_from_i64(3),vc_number(35,10),vc_number(6,100));
    if hidden {vc_wall("Wall.partition-a",vc_number(12,10),vc_number(-19,10),vc_number(6,100),vc_number(11,10));
        vc_wall("Wall.partition-b",vc_number(12,10),vc_number(16,10),vc_number(6,100),vc_number(14,10));}
    let count=vc_box_count-1;let vertices=vc_box_count*36;let bytes=256+count*128+vertices*72;let data=alloc(bytes);
    vc_copy(data,"PBENV001",8);store64(data+8,count);store64(data+16,vertices);store64(data+24,vertices);
    store64(data+64,vc_number(-35,10));store64(data+72,f64_from_i64(-3));store64(data+80,vc_number(35,10));store64(data+88,f64_from_i64(3));
    vc_copy(data+128,"Native visual-control curriculum",32);let full=data+256+count*128;let overview=full+vertices*36;let i=0;
    while i<vc_box_count {let record=vc_boxes+i*128;if i {vc_copy(data+256+(i-1)*128,record,96);}
        vc_mesh_box(record,full+i*36*36,overview+i*36*36);i=i+1;}
    vc_write(path,data,bytes);syscall(11,data,bytes,0,0,0,0);syscall(11,vc_boxes,32*128,0,0,0,0);return 0;
}
fn vc_set_number(node,value) {vc_require(node,"missing curriculum field");store64(node,6);store64(node+8,value);store64(node+16,0);return 0;}
fn vc_case(path,template,seed,hidden) {
    vc_rng=seed&2147483647;let root=vc_json_file(template);let id=pj_get(root,"id");let name=vc_concat("pixel-native-",vc_int(seed));vc_require(pj_kind(id)==2,"curriculum case ID is missing");store64(id+8,name);store64(id+16,pl_size(name));let objects=pj_get(root,"objects");let first=pj_value(objects);
    vc_require(pj_kind(objects)==3 && first,"curriculum case must contain an object");store64(objects+16,1);store64(first+24,0);
    let position=pj_get(first,"position");let x=vc_uniform(vc_number(235,100),vc_number(285,100));let y=vc_uniform(vc_number(-4,10),vc_number(4,10));
    if hidden {x=vc_number(27,10);y=vc_number(19,10);}vc_set_number(pj_index(position,0),x);vc_set_number(pj_index(position,1),y);
    let container=pj_get(root,"container");position=pj_get(container,"position");vc_set_number(pj_index(position,0),vc_number(5,10));vc_random();let side=-1;
    if vc_rng&1 {side=1;}vc_set_number(pj_index(position,1),vc_number(side*27,100));
    let fixed=pj_get(container,"fixed");if !fixed {fixed=pj_node(5,1,0);store64(fixed+32,"fixed");store64(fixed+40,5);store64(fixed+24,pj_value(container));store64(container+8,fixed);store64(container+16,pj_count(container)+1);}else {store64(fixed+8,1);}
    let scenery=pj_get(root,"scenery");if scenery {store64(scenery+8,0);store64(scenery+16,0);}
    let text=alloc(16384);let builder=alloc(32);pl_builder(builder,text,16384);pj_emit(builder,root);pl_char(builder,10);
    vc_require(!pj_error && !load64(builder+24),"cannot construct curriculum case");vc_write(path,text,load64(builder+8));syscall(11,text,16384,0,0,0,0);syscall(11,builder,32,0,0,0,0);return 0;
}
