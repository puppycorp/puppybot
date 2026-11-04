// Experimental isolated control guard. No old binary imports this module.
// The expected manifest digest is caller-supplied, not an authenticity proof.
import "host.flex";
global sg_manifest=0;
global sg_expected=0;
global sg_case_hashes=0;
global sg_env_hashes=0;

fn sg_string(root,key) {
    let node=pj_get(root,key);vc_require(pj_kind(node)==2,"guard: missing string");return pj_value(node);
}
fn sg_integer(root,key) {
    let node=pj_get(root,key);vc_require(pj_kind(node)==1,"guard: missing integer");return pj_value(node);
}
fn sg_hash_ok(text) {
    if !text || pl_size(text)!=64 {return 0;}let i=0;while i<64 {let c=load8(text+i);if !((c>=48 && c<=57) || (c>=97 && c<=102)) {return 0;}i=i+1;}return 1;
}
fn sg_path(root,leaf) {
    let n=pl_size(root);let m=pl_size(leaf);let out=alloc(n+m+2);vc_copy(out,root,n);store8(out+n,47);vc_copy(out+n+1,leaf,m+1);return out;
}
fn sg_free_file(file) {
    let size=load64(file+8);syscall(11,load64(file),size+1,0,0,0,0);syscall(11,load64(file+16),65,0,0,0,0);syscall(11,file,24,0,0,0,0);return 0;
}
// Copy file bytes to private memory before validation; the simulator later
// receives exactly these bytes even if the source path or symlink changes.
fn sg_read(path,limit) {
    let data=vc_map_bounded(path,limit);let size=vc_size;let out=alloc(24);let bytes=alloc(size+1);
    vc_copy(bytes,data,size);store8(bytes+size,0);syscall(11,data,size,0,0,0,0);
    store64(out,bytes);store64(out+8,size);store64(out+16,vc_digest(bytes,size));return out;
}
fn sg_init(path,expected) {
    vc_require(path && expected && sg_hash_ok(expected),"guard: pinned reservation manifest required");
    sg_manifest=path;sg_expected=expected;return 0;
}
fn sg_manifest_read() {
    let file=sg_read(sg_manifest,4194304);vc_require(pl_equal(load64(file+16),sg_expected),"guard: reservation digest mismatch");
    let old=pj_arena;let cap=pj_capacity;pj_arena=0;pj_capacity=2097152;
    let root=pj_parse(load64(file),load64(file+8));vc_require(root && pj_kind(root)==4,"guard: malformed reservation");
    vc_require(pl_equal(sg_string(root,"status"),"reserved_not_evaluated") && pl_equal(sg_string(root,"task"),"virtual-fetch") && sg_integer(root,"gamesPerLevel")==32,"guard: invalid reservation header");
    let rows=pj_get(root,"rows");vc_require(pj_kind(rows)==3 && pj_count(rows)==160,"guard: reservation must contain 160 rows");
    if !sg_case_hashes {sg_case_hashes=alloc(160*65);sg_env_hashes=alloc(160*65);}let seen=alloc(160);pb_zero(seen,160);let i=0;
    let expected=alloc(128);let builder=alloc(32);
    while i<160 {
        let row=pj_index(rows,i);vc_require(pj_kind(row)==4,"guard: malformed reservation row");
        let level=sg_integer(row,"level");let index=sg_integer(row,"index");vc_require(level>=1 && level<=5 && index>=0 && index<32,"guard: invalid reservation index");
        let slot=(level-1)*32+index;vc_require(!load8(seen+slot),"guard: duplicate reservation row");store8(seen+slot,1);
        let layout=226+index;if level>=4 {layout=227+2*index;}
        vc_require(sg_integer(row,"seed")==1700000000+level*100+index && sg_integer(row,"layoutId")==layout,"guard: invalid reservation mapping");
        pl_builder(builder,expected,128);pl_text(builder,"generated/");pl_int(builder,layout);pl_char(builder,47);pl_int(builder,index%16);
        vc_require(!load64(builder+24),"guard: reservation path too long");
        vc_require(pl_equal(sg_string(row,"scene"),expected),"guard: invalid reservation scene path");
        let case_hash=sg_string(row,"caseSHA256");let env_hash=sg_string(row,"environmentSHA256");
        vc_require(sg_hash_ok(case_hash) && sg_hash_ok(env_hash),"guard: invalid reservation hash");
        vc_copy(sg_case_hashes+i*65,case_hash,65);vc_copy(sg_env_hashes+i*65,env_hash,65);i=i+1;
    }
    syscall(11,pj_arena,pj_capacity,0,0,0,0);pj_arena=old;pj_capacity=cap;pj_error=0;
    syscall(11,seen,160,0,0,0,0);syscall(11,expected,128,0,0,0,0);syscall(11,builder,32,0,0,0,0);sg_free_file(file);return 0;
}
fn sg_snapshot(scene) {
    vc_require(scene && sg_manifest && sg_expected,"guard: explicit scene and pinned manifest required");sg_manifest_read();
    let path=sg_path(scene,"layout.json");let layout=sg_read(path,4194304);syscall(11,path,pl_size(path)+1,0,0,0,0);
    let old=pj_arena;let cap=pj_capacity;pj_arena=0;pj_capacity=2097152;
    let root=pj_parse(load64(layout),load64(layout+8));vc_require(root && pj_kind(root)==4,"guard: malformed scene metadata");
    let fit=pj_get(root,"fit");vc_require(pj_kind(fit)==5 && pj_value(fit),"guard: scene not marked for fitting");
    let reserved=pj_get(root,"reservedHeldOut");vc_require(!reserved || (pj_kind(reserved)==5 && !pj_value(reserved)),"guard: reserved scene role");
    syscall(11,pj_arena,pj_capacity,0,0,0,0);pj_arena=old;pj_capacity=cap;pj_error=0;
    path=sg_path(scene,"case.json");let case_file=sg_read(path,33554432);syscall(11,path,pl_size(path)+1,0,0,0,0);
    path=sg_path(scene,"environment.bin");let environment=sg_read(path,33554432);syscall(11,path,pl_size(path)+1,0,0,0,0);
    let i=0;while i<160 {
        vc_require(!pl_equal(load64(case_file+16),sg_case_hashes+i*65) && !pl_equal(load64(environment+16),sg_env_hashes+i*65),"guard: exact reserved scene content");i=i+1;
    }
    let snapshot=alloc(24);store64(snapshot,case_file);store64(snapshot+8,environment);store64(snapshot+16,layout);return snapshot;
}
fn sg_write_one(world,name,file) {
    let path=sg_path(world,name);vc_write(path,load64(file),load64(file+8));let actual=vc_file_sha(path);
    vc_require(pl_equal(actual,load64(file+16)),"guard: copied scene digest mismatch");
    syscall(11,actual,65,0,0,0,0);syscall(11,path,pl_size(path)+1,0,0,0,0);return 0;
}
fn sg_release(snapshot) {
    sg_free_file(load64(snapshot));sg_free_file(load64(snapshot+8));sg_free_file(load64(snapshot+16));syscall(11,snapshot,24,0,0,0,0);return 0;
}
fn sg_write(world,snapshot) {
    sg_write_one(world,"case.json",load64(snapshot));sg_write_one(world,"environment.bin",load64(snapshot+8));
    sg_write_one(world,"layout.json",load64(snapshot+16));return sg_release(snapshot);
}
