// Private research guard for fit/validation chase collection only. The policy
// must already be prepared from both pinned reservation manifests.
import "host.flex";

global vg_policy = 0;
global vg_expected_sha = 0;
global vg_directory = 0;
global vg_selection_manifest = 0;
global vg_heldout_manifest = 0;

fn vg_is_hash(text) {
    if !text || pl_size(text)!=64 {return 0;}let i=0;
    while i<64 {let c=load8(text+i);if !((c>=48 && c<=57) || (c>=97 && c<=102)) {return 0;}i=i+1;}return 1;
}
fn vg_hash_field(object,name) {
    let node=pj_get(object,name);vc_require(pj_kind(node)==2 && vg_is_hash(pj_value(node)),"invalid guarded digest");return pj_value(node);
}
fn vg_text_field(object,name) {
    let node=pj_get(object,name);vc_require(pj_kind(node)==2,"guarded string required");return pj_value(node);
}
fn vg_denied(array,hash) {
    vc_require(pj_kind(array)==3 && pj_count(array)>0 && pj_count(array)<=320,"invalid reserved hash list");let i=0;
    while i<pj_count(array) {let node=pj_index(array,i);vc_require(pj_kind(node)==2 && vg_is_hash(pj_value(node)),"invalid reserved hash");if pl_equal(pj_value(node),hash) {return 1;}i=i+1;}return 0;
}
// Verify both reservation manifests in native code and require the policy to
// deny every recorded case/environment hash. The caller still must pin the
// correct manifest identities in an independently reviewed plan.
fn vg_manifest(path,expected,selection,cases,environments,first,count) {
    vc_require(path && vg_is_hash(expected),"reservation manifest and digest required");
    let mapped=vc_map(path);let size=vc_size;vc_require(size<=4194304,"reservation manifest exceeds 4 MiB");
    let data=alloc(size);vc_copy(data,mapped,size);syscall(11,mapped,size,0,0,0,0);
    vc_require(pl_equal(vc_digest(data,size),expected),"reservation manifest digest differs");
    let old_arena=pj_arena;let old_capacity=pj_capacity;let old_used=pj_used;
    pj_capacity=2097152;pj_arena=alloc(pj_capacity);let root=pj_parse(data,size);vc_require(root,"invalid reservation manifest JSON");
    let status="reserved_not_evaluated";if selection {status="selection_not_evaluated";}
    vc_require(pl_equal(vg_text_field(root,"status"),status) && pl_equal(vg_text_field(root,"task"),"virtual-fetch") && vc_json_int(root,"gamesPerLevel",0)==32,"reservation manifest header differs");
    let rows=pj_get(root,"rows");vc_require(pj_kind(rows)==3 && pj_count(rows)==160,"reservation manifest needs 160 rows");
    let seen=alloc(160);pb_zero(seen,160);let i=0;
    while i<160 {
        let row=pj_index(rows,i);let level=vc_json_int(row,"level",0);let index=vc_json_int(row,"index",0);
        vc_require(level>=1 && level<=5 && index>=0 && index<32,"reservation index differs");let slot=(level-1)*32+index;
        vc_require(!load8(seen+slot),"duplicate reservation index");store8(seen+slot,1);
        let layout=226+index;let seed=1700000000+100*level+index;if level>=4 {layout=227+2*index;}
        if selection {layout=290+index;seed=1800000000+100*level+index;if level>=4 {layout=291+2*index;}}
        let scene=vc_path(vc_path("generated",vc_int(layout)),vc_int(index%16));
        vc_require(vc_json_int(row,"layoutId",0)==layout && vc_json_int(row,"seed",0)==seed && pl_equal(vg_text_field(row,"scene"),scene),"reservation mapping differs");
        vc_require(seed<first || seed>=first+count,"collection seed overlaps a reserved game");
        vc_require(vg_denied(cases,vg_hash_field(row,"caseSHA256")) && vg_denied(environments,vg_hash_field(row,"environmentSHA256")),"guard policy omits reserved scene hash");i=i+1;
    }
    let arena=pj_arena;pj_arena=old_arena;pj_capacity=old_capacity;pj_used=old_used;
    syscall(11,arena,2097152,0,0,0,0);syscall(11,data,size,0,0,0,0);syscall(11,seen,160,0,0,0,0);return 0;
}
fn vg_layout(data,size,fit) {
    let old_arena=pj_arena;let old_capacity=pj_capacity;let old_used=pj_used;
    pj_capacity=131072;pj_arena=alloc(pj_capacity);let root=pj_parse(data,size);vc_require(root,"invalid scene metadata JSON");
    let node=pj_get(root,"fit");vc_require(pj_kind(node)==5 && pj_value(node)==fit,"scene fit/validation role differs");
    node=pj_get(root,"layoutId");vc_require(pj_kind(node)==1,"scene layout ID required");let id=pj_value(node);
    vc_require(id>=0 && (id<226 || id>353),"reserved heldout or selection layout rejected");
    node=pj_get(root,"reservedHeldOut");if node {vc_require(pj_kind(node)==5 && !pj_value(node),"heldout marker rejected");}
    node=pj_get(root,"selectionOnly");if node {vc_require(pj_kind(node)==5 && !pj_value(node),"selection marker rejected");}
    let scratch=pj_arena;pj_arena=old_arena;pj_capacity=old_capacity;pj_used=old_used;syscall(11,scratch,131072,0,0,0,0);return 0;
}
// Snapshot to process-owned memory before hashing, role-checking and writing
// those same bytes. Different source files are not an atomic snapshot.
fn vg_copy(source,target,expected,denied,fit) {
    vc_require(vg_is_hash(expected),"invalid scene digest");let mapped=vc_map(source);let n=vc_size;
    vc_require(n<=33554432 && (fit<0 || n<=4194304),"guarded scene file exceeds size limit");let buffer=alloc(n);vc_copy(buffer,mapped,n);syscall(11,mapped,n,0,0,0,0);
    let hash=vc_digest(buffer,n);vc_require(pl_equal(hash,expected),"scene bytes differ from guarded plan");
    if denied {vc_require(!vg_denied(denied,hash),"reserved scene bytes rejected");}
    if fit>=0 {vg_layout(buffer,n,fit);}vc_write(target,buffer,n);syscall(11,buffer,n,0,0,0,0);return 0;
}
fn vg_prepare(output,catalog,episodes,validation,seed) {
    vc_require(vg_policy && vg_is_hash(vg_expected_sha) && vg_selection_manifest && vg_heldout_manifest,"pinned scene guard policy and reservation manifests required");
    vc_require(catalog && episodes>=2 && episodes<=128 && validation>=1 && validation<episodes && seed>=0 && seed<=2147483647-(episodes-1),"guard requires explicit catalog, split and bounded seed");
    let mapped=vc_map(vg_policy);let size=vc_size;vc_require(size<=4194304,"guard policy exceeds 4 MiB");let data=alloc(size);vc_copy(data,mapped,size);syscall(11,mapped,size,0,0,0,0);
    vc_require(pl_equal(vc_digest(data,size),vg_expected_sha),"scene guard policy digest differs");
    let old_arena=pj_arena;let old_capacity=pj_capacity;let old_used=pj_used;
    pj_capacity=2097152;pj_arena=alloc(pj_capacity);let root=pj_parse(data,size);vc_require(root,"invalid scene guard policy JSON");
    vc_require(pl_equal(vg_text_field(root,"schema"),"puppybot.native-scene-guard.v1"),"scene guard schema differs");
    vc_require(vc_json_int(root,"episodes",0)==episodes && vc_json_int(root,"validation",0)==validation && vc_json_int(root,"seed",0)==seed,"scene guard split or seed differs");
    let selection_sha=vg_hash_field(root,"selectionManifestSHA256");let heldout_sha=vg_hash_field(root,"heldoutManifestSHA256");
    let cases=pj_get(root,"denyCases");let environments=pj_get(root,"denyEnvironments");let rows=pj_get(root,"rows");
    vc_require(pj_kind(cases)==3 && pj_count(cases)>0 && pj_count(cases)<=320 && pj_kind(environments)==3 && pj_count(environments)>0 && pj_count(environments)<=320,"reserved hash lists required");
    vc_require(pj_kind(rows)==3 && pj_count(rows)==episodes,"scene guard row count differs");
    vg_manifest(vg_selection_manifest,selection_sha,1,cases,environments,seed,episodes);vg_manifest(vg_heldout_manifest,heldout_sha,0,cases,environments,seed,episodes);
    vg_directory=vc_path(output,"guarded-scenes");vc_mkdir(vg_directory);let i=0;
    while i<episodes {
        let row=pj_index(rows,i);let fit=i<episodes-validation;vc_require(vc_json_int(row,"index",0)==i && vc_json_int(row,"seed",0)==seed+i,"scene guard row identity differs");
        let role=vg_text_field(row,"role");if fit {vc_require(pl_equal(role,"fit"),"scene guard fitting role differs");}else {vc_require(pl_equal(role,"validation"),"scene guard validation role differs");}
        let source=vc_path(catalog,vc_int(i));let target=vc_path(vg_directory,vc_int(i));vc_mkdir(target);
        vg_copy(vc_path(source,"case.json"),vc_path(target,"case.json"),vg_hash_field(row,"caseSHA256"),cases,-1);
        vg_copy(vc_path(source,"environment.bin"),vc_path(target,"environment.bin"),vg_hash_field(row,"environmentSHA256"),environments,-1);
        vg_copy(vc_path(source,"layout.json"),vc_path(target,"layout.json"),vg_hash_field(row,"layoutSHA256"),0,fit);i=i+1;
    }
    let arena=pj_arena;pj_arena=old_arena;pj_capacity=old_capacity;pj_used=old_used;syscall(11,arena,2097152,0,0,0,0);syscall(11,data,size,0,0,0,0);return 1;
}
