import "../control/host.flex";
import "../sim/seek-projection.flex";
fn main(argc,argv) {
    vc_init(argc,argv);let camera=alloc(96);let point=alloc(24);let box=alloc(32);
    store64(camera+24+16,PB_ONE);store64(camera+48,PB_ONE);store64(camera+72+8,PB_ONE);store64(point+16,PB_ONE);
    store64(box,318);store64(box+8,238);store64(box+16,322);store64(box+24,242);
    vc_require(ps_seek_projection_match(box,camera,point),"centered prop was not matched");
    store64(box,0);store64(box+8,0);store64(box+16,10);store64(box+24,10);
    vc_require(!ps_seek_projection_match(box,camera,point),"unrelated detection matched the prop");
    store64(point+16,vc_number(-1,1));vc_require(!ps_seek_projection_match(box,camera,point),"behind-camera prop was matched");
    // Frame 2075 from the failed collection audit: the bright component's
    // bounds do not contain the actual prop center, even with the 12px margin.
    store64(camera,vc_number(2733,1000));store64(camera+8,vc_number(25,1000));store64(camera+16,vc_number(451,1000));
    store64(camera+24,vc_number(630634,1000000));store64(camera+32,vc_number(-388182,1000000));store64(camera+40,vc_number(-672026,1000000));
    store64(camera+48,vc_number(-524194,1000000));store64(camera+56,vc_number(-851598,1000000));store64(camera+64,0);
    store64(camera+72,vc_number(-572295,1000000));store64(camera+80,vc_number(352271,1000000));store64(camera+88,vc_number(-740529,1000000));
    store64(point,vc_number(2889309,1000000));store64(point+8,vc_number(-288779,1000000));store64(point+16,vc_number(11950,1000000));
    store64(box,452);store64(box+8,315);store64(box+16,474);store64(box+24,322);
    vc_require(!ps_seek_projection_match(box,camera,point),"recorded mismatched detection was accepted");
    store64(box+24,345);vc_require(ps_seek_projection_match(box,camera,point),"detection covering recorded projection was rejected");
    pl_print(1,"Seek projection association checks passed.\n");return 0;
}
