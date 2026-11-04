// Private, snapshot-only bootstrap. This binary cannot start a simulator,
// policy, collector or trainer. The reviewed synthetic allowlist digest is
// compiled into the executable; the command line cannot replace it.
import "@HOST@";

global ab_bytes = 0;
global ab_total = 0;

fn ab_hash(text) {
    if !text || pl_size(text)!=64 {return 0;}let i=0;
    while i<64 {let c=load8(text+i);if !((c>=48 && c<=57) || (c>=97 && c<=102)) {return 0;}i=i+1;}return 1;
}
fn ab_text(root,name) {
    let node=pj_get(root,name);vc_require(pj_kind(node)==2,"bootstrap string required");return pj_value(node);
}
fn ab_digest(root,name) {
    let value=ab_text(root,name);vc_require(ab_hash(value),"bootstrap digest invalid");return value;
}
fn ab_layout(data,size,fit) {
    let old_arena=pj_arena;let old_capacity=pj_capacity;let old_used=pj_used;
    pj_capacity=131072;pj_arena=alloc(pj_capacity);let root=pj_parse(data,size);vc_require(root,"invalid bootstrap layout JSON");
    let node=pj_get(root,"fit");vc_require(pj_kind(node)==5 && pj_value(node)==fit,"bootstrap layout split differs");
    node=pj_get(root,"layoutId");vc_require(pj_kind(node)==1,"bootstrap layout ID required");let id=pj_value(node);
    vc_require(id>=0 && (id<226 || id>353),"reserved bootstrap layout rejected");
    node=pj_get(root,"reservedHeldOut");if node {vc_require(pj_kind(node)==5 && !pj_value(node),"heldout marker rejected");}
    node=pj_get(root,"selectionOnly");if node {vc_require(pj_kind(node)==5 && !pj_value(node),"selection marker rejected");}
    let arena=pj_arena;pj_arena=old_arena;pj_capacity=old_capacity;pj_used=old_used;syscall(11,arena,131072,0,0,0,0);return 0;
}
// Copy each source into private memory before validating and eventually
// writing those same bytes. The three source files are not an atomic snapshot.
fn ab_capture(path,expected,fit) {
    let mapped=vc_map_bounded(path,4194304);let size=vc_size;
    ab_total=ab_total+size;vc_require(ab_total<=67108864,"bootstrap snapshot exceeds 64 MiB");
    let data=alloc(size);vc_copy(data,mapped,size);syscall(11,mapped,size,0,0,0,0);
    vc_require(pl_equal(vc_digest(data,size),expected),"bootstrap scene bytes differ from allowlist");
    if fit>=0 {ab_layout(data,size,fit);}ab_bytes=size;return data;
}
fn ab_write(path,data,size) {
    vc_write(path,data,size);let expected=vc_digest(data,size);
    vc_require(pl_equal(vc_file_sha(path),expected),"bootstrap snapshot readback differs");return 0;
}
fn ab_snapshot(policy,catalog,output) {
    let mapped=vc_map_bounded(policy,4194304);let size=vc_size;let data=alloc(size);vc_copy(data,mapped,size);syscall(11,mapped,size,0,0,0,0);
    vc_require(pl_equal(vc_digest(data,size),"@POLICY_SHA@"),"bootstrap allowlist identity differs from executable");
    pj_capacity=2097152;pj_arena=alloc(pj_capacity);let root=pj_parse(data,size);vc_require(root,"invalid bootstrap allowlist JSON");
    vc_require(pl_equal(ab_text(root,"schema"),"puppybot.positive-bootstrap.v1") && pl_equal(ab_text(root,"status"),"synthetic_only"),"bootstrap allowlist header differs");
    let episodes=vc_json_int(root,"episodes",0);let validation=vc_json_int(root,"validation",0);let seed=vc_json_int(root,"seed",0);
    vc_require(episodes>=2 && episodes<=128 && validation>=1 && validation<episodes && seed>=0 && seed<=2147483647-(episodes-1),"bootstrap split or seed invalid");
    let last=seed+episodes-1;vc_require((last<1700000100 || seed>1700000531) && (last<1800000100 || seed>1800000531),"bootstrap seed range reserved");
    let rows=pj_get(root,"rows");vc_require(pj_kind(rows)==3 && pj_count(rows)==episodes,"bootstrap row count differs");
    let buffers=alloc(episodes*48);let cases=alloc(episodes*8);let environments=alloc(episodes*8);let i=0;
    while i<episodes {
        let row=pj_index(rows,i);let fit=i<episodes-validation;
        vc_require(vc_json_int(row,"index",0)==i && vc_json_int(row,"seed",0)==seed+i,"bootstrap row identity differs");
        let role=ab_text(row,"role");if fit {vc_require(pl_equal(role,"fit"),"bootstrap fitting role differs");}else {vc_require(pl_equal(role,"validation"),"bootstrap validation role differs");}
        let case_hash=ab_digest(row,"caseSHA256");let environment_hash=ab_digest(row,"environmentSHA256");let layout_hash=ab_digest(row,"layoutSHA256");
        let prior=0;while prior<i {vc_require(!pl_equal(case_hash,load64(cases+prior*8)) && !pl_equal(environment_hash,load64(environments+prior*8)),"duplicate bootstrap scene bytes");prior=prior+1;}
        store64(cases+i*8,case_hash);store64(environments+i*8,environment_hash);
        let source=vc_path(catalog,vc_int(i));let base=buffers+i*48;
        store64(base,ab_capture(vc_path(source,"case.json"),case_hash,-1));store64(base+8,ab_bytes);
        store64(base+16,ab_capture(vc_path(source,"environment.bin"),environment_hash,-1));store64(base+24,ab_bytes);
        store64(base+32,ab_capture(vc_path(source,"layout.json"),layout_hash,fit));store64(base+40,ab_bytes);i=i+1;
    }
    // No filesystem output exists until every approved byte buffer passed.
    vc_mkdir(output);ab_write(vc_path(output,"allowlist.json"),data,size);
    let scenes=vc_path(output,"scenes");vc_mkdir(scenes);i=0;
    while i<episodes {
        let target=vc_path(scenes,vc_int(i));vc_mkdir(target);let base=buffers+i*48;
        ab_write(vc_path(target,"case.json"),load64(base),load64(base+8));
        ab_write(vc_path(target,"environment.bin"),load64(base+16),load64(base+24));
        ab_write(vc_path(target,"layout.json"),load64(base+32),load64(base+40));i=i+1;
    }
    return 1;
}
fn main(argc,argv) {
    vc_init(argc,argv);
    // The entire command surface is fixed: arbitrary control commands,
    // direct scene paths, packed data, policy paths and extra flags fail
    // before output creation. This prototype executes no child process.
    vc_require(argc==5 && pl_equal(load64(argv+8),"snapshot"),"bootstrap permits only snapshot ALLOWLIST CATALOG OUTPUT");
    ab_snapshot(load64(argv+16),load64(argv+24),load64(argv+32));
    pl_print(1,"synthetic approved scene snapshots written\n");return 0;
}
