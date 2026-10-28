// Native dependency adaptation for the shared simulator. Model geometry is an
// existing simulator asset; visual-control builds never invoke its exporters.
import "host.flex";
global vp_source=0;
global vp_project=0;
global vp_seen=0;
global vp_records=0;
global vp_record_text=0;
fn vc_directories(path) {let copy=vc_string(path);let i=1;while load8(copy+i) {if load8(copy+i)==47 {store8(copy+i,0);let status=syscall(83,copy,448,0,0,0,0);vc_require(!status || status== -17,"cannot create build directory");store8(copy+i,47);}i=i+1;}let status=syscall(83,copy,448,0,0,0,0);vc_require(!status || status== -17,"cannot create build directory");return 0;}
fn vc_parent(path) {let out=vc_string(path);let i=pl_size(out);while i && load8(out+i)!=47 {i=i-1;}store8(out+i,0);return out;}
fn vc_realpath(path) {let out=alloc(4096);let function=ffi_symbol(ffi_open("libc.so.6"),"realpath");vc_require(ffi_call(function,path,out,0,0,0,0),vc_concat("missing dependency ",path));return out;}
fn vc_import_source(path) {
    path=vc_realpath(path);vc_require(pl_starts(path,vc_concat(vp_source,"/")),"shared dependency import escaped its root");let relative=path+pl_size(vp_source)+1;let i=0;
    while i<load64(vp_seen) {if pl_equal(load64(vp_seen+8+i*8),path) {return 0;}i=i+1;}vc_add(vp_seen,path);
    let original=vc_text_file(path);let adapted=original;
    if pl_equal(relative,"lib/f64.flex") {adapted=vc_concat(vc_concat("import \"",vc_path(vp_project,"flex/core/words.flex")),"\";\n");}
    else if pl_equal(relative,"lib/gpu.flex") {
        adapted=vc_replace(adapted,"lowering f64_add \"f64.add\" \"native-x86_64\";\n","");adapted=vc_replace(adapted,"lowering f64_sub \"f64.sub\" \"native-x86_64\";\n","");
        adapted=vc_replace(adapted,"lowering f64_mul \"f64.mul\" \"native-x86_64\";\n","");adapted=vc_replace(adapted,"lowering f64_div \"f64.div\" \"native-x86_64\";\n","");adapted=vc_replace(adapted,"lowering f64_sqrt \"f64.sqrt\" \"native-x86_64\";\n","");
    }else if pl_equal(relative,"libs/physics/collision.flex") {
        adapted=vc_replace(adapted,"            ph_collide_pair(w,a,ph_shape(w,j),ph_scratch(w));","            if load64(ph_body(w,load64(a))+112) || load64(ph_body(w,load64(ph_shape(w,j)))+112) { ph_collide_pair(w,a,ph_shape(w,j),ph_scratch(w)); }");
    }
    let target=vc_path(vc_path(vp_project,"build/flex/sim/library"),relative);vc_directories(vc_parent(target));vc_save_text(target,adapted);
    if load64(vp_seen)>1 {pl_char(vp_records,44);}pj_text(vp_records,relative);pl_text(vp_records,":{\"sourceSha256\":");pj_text(vp_records,vc_digest(original,pl_size(original)));pl_text(vp_records,",\"adaptedSha256\":");pj_text(vp_records,vc_digest(adapted,pl_size(adapted)));pl_char(vp_records,125);
    i=0;while load8(original+i) {
        let skip=0;if pl_starts(original+i,"import \"") {skip=8;}if pl_starts(original+i,"extend \"") {skip=8;}
        if skip {let end=i+skip;while load8(original+end) && load8(original+end)!=34 {end=end+1;}vc_require(load8(original+end)==34,"invalid shared import");
            let name=alloc(end-i-skip+1);vc_copy(name,original+i+skip,end-i-skip);vc_import_source(vc_path(vc_parent(path),name));i=end;}i=i+1;
    }return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"prepare PROJECT FLEXSCRIPT_SOURCE");vp_project=vc_realpath(load64(argv+8));vp_source=vc_realpath(load64(argv+16));vp_seen=vc_args();
    vp_records=alloc(32);vp_record_text=alloc(131072);pl_builder(vp_records,vp_record_text,131072);pl_char(vp_records,123);
    vc_import_source(vc_path(vp_source,"libs/render.flex"));vc_import_source(vc_path(vp_source,"libs/physics/physics.flex"));pl_text(vp_records,"}\n");vc_require(!load64(vp_records+24),"dependency receipt exceeded limit");
    vc_write(vc_path(vp_project,"build/flex/sim/dependencies.json"),vp_record_text,load64(vp_records+8));
    let out=alloc(8192);let b=alloc(32);pl_builder(b,out,8192);pl_text(b,"import ");pj_text(b,vc_path(vp_project,"build/flex/sim/library/libs/render.flex"));pl_text(b,";\nimport ");pj_text(b,vc_path(vp_project,"build/flex/sim/library/libs/physics/physics.flex"));pl_text(b,";\n");vc_write(vc_path(vp_project,"build/flex/sim/dependencies.flex"),out,load64(b+8));
    let simulator=vc_text_file(vc_path(vp_project,"flex/sim/main.flex"));simulator=vc_replace(simulator,"import \"",vc_concat("import \"",vc_concat(vc_path(vp_project,"flex/sim"),"/")));
    simulator=vc_replace(simulator,"fn main(argc, argv)","fn ps_sim_test_entry(argc, argv)");vc_save_text(vc_path(vp_project,"build/flex/control/sim-test-library.flex"),simulator);
    let model=vc_map(vc_path(vp_project,"build/flex/sim/puppybot.bin"));vc_require(load64(model)==load64("PBSIM002"),"shared simulator model asset must be prepared first");pl_print(1,"Prepared shared simulator dependencies without Python.\n");return 0;
}
