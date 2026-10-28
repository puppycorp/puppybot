// Merge audited dense histories while preserving source order within each split.
import "../../../flex/control/dataset.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc>=6 && argc<=34 && !((argc-2)%2),"merge-dense-many OUTPUT DATA RUN [DATA RUN ...]");
    let count=(argc-2)/2;let sources=alloc(count*8);let roots=alloc(count*8);let hashes=alloc(count*8);let episodes=0;let fitting=0;let length=0;let source=0;let libc=ffi_open("libc.so.6");let resolve=ffi_symbol(libc,"realpath");let release=ffi_symbol(libc,"free");vc_require(resolve && release,"cannot resolve source histories");
    while source<count {let path=vc_absolute(load64(argv+(2+source*2)*8));let data=vd_map(path);let bytes=vc_size;vc_require(bytes>=32,"invalid dense source header");let n=load64(data+8);let fit=load64(data+16);let steps=load64(data+24);
        vc_require(vd_row_bytes(data)==56 && n>=2 && n<=vd_episode_limit(data) && fit>=1 && fit<n && steps>=1 && steps<=512 && bytes==32+n*steps*21224,"invalid dense source dataset");
        store64(sources+source*8,data);store64(roots+source*8,vc_absolute(load64(argv+(3+source*2)*8)));store64(hashes+source*8,vc_digest(data,bytes));episodes=episodes+n;fitting=fitting+fit;length=pb_max(length,steps);source=source+1;
    }
    let size=32+episodes*length*21224;vc_require(episodes<=1024 && size<=8589934592,"dense aggregate exceeds limits");let output=vc_absolute(load64(argv+8));vc_mkdir(output);
    let partial=vc_path(output,"data.partial.bin");let fd=syscall(2,partial,0x800c2,384,0,0,0);vc_require(fd>=0 && !syscall(77,fd,size,0,0,0,0),"cannot allocate aggregate data");let merged=syscall(9,0,size,3,1,fd,0);vc_require(merged>0,"cannot map aggregate data");
    let magic="PVDATA03";if episodes>256 || size>2147483648 {magic="PVDATA04";}vc_copy(merged,magic,8);store64(merged+8,episodes);store64(merged+16,fitting);store64(merged+24,length);
    let text=alloc(131072);let b=alloc(32);pl_builder(b,text,131072);pl_text(b,"{\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"preservesFitValidationSplits\":true,\"sourceSHA256\":[");
    source=0;while source<count {if source {pl_char(b,44);}pj_text(b,load64(hashes+source*8));source=source+1;}pl_text(b,"],\"records\":[");
    let split=0;let target=0;while split<2 {source=0;while source<count {let data=load64(sources+source*8);let steps=load64(data+24);let i=0;let end=load64(data+16);if split {i=end;end=load64(data+8);}
        while i<end {let from=data+32+i*steps*21224;let to=merged+32+target*length*21224;vc_copy(to,from,steps*21168);vc_copy(to+length*21168,from+steps*21168,steps*56);
            let original=vc_path(load64(roots+source*8),vc_concat("expert-",vc_int(i)));let alias=vc_path(output,vc_concat("expert-",vc_int(target)));let canonical=ffi_call(resolve,original,0,0,0,0,0);vc_require(canonical,vc_concat("cannot resolve aggregate source history: ",original));let initial=vc_path(canonical,"initial.json");let decisions=vc_path(canonical,"decisions.jsonl");let initial_status=syscall(21,initial,4,0,0,0,0);let decisions_status=syscall(21,decisions,4,0,0,0,0);if initial_status {vc_require(0,vc_concat("aggregate source initial file unavailable: ",initial));}if decisions_status {vc_require(0,vc_concat("aggregate source decisions file unavailable: ",decisions));}vc_require(!syscall(88,canonical,alias,0,0,0,0),"cannot link aggregate history");ffi_call(release,canonical,0,0,0,0,0);
            if target {pl_char(b,44);}pl_text(b,"{\"index\":");pl_int(b,target);pl_text(b,",\"source\":");pl_int(b,source);pl_text(b,",\"sourceIndex\":");pl_int(b,i);pl_text(b,",\"fit\":");pj_bool_text(b,!split);pl_char(b,125);target=target+1;i=i+1;
        }source=source+1;}split=split+1;}
    vc_require(target==episodes && !load64(b+24),"aggregate records exceeded limit");vc_require(!syscall(26,merged,size,4,0,0,0) && !syscall(74,fd,0,0,0,0,0),"cannot synchronize aggregate data");
    let checksum=vc_digest(merged,size);syscall(11,merged,size,0,0,0,0);syscall(3,fd,0,0,0,0,0);vc_require(!syscall(82,partial,vc_path(output,"data.bin"),0,0,0,0),"cannot publish aggregate data");
    pl_text(b,"],\"episodes\":");pl_int(b,episodes);pl_text(b,",\"fitTrajectories\":");pl_int(b,fitting);pl_text(b,",\"sequenceLength\":");pl_int(b,length);pl_text(b,",\"dataSHA256\":");pj_text(b,checksum);pl_text(b,"}\n");vc_require(!load64(b+24),"aggregate receipt exceeded limit");vc_write(vc_path(output,"report.json"),text,load64(b+8));return 0;
}
