// File/process support for the visual-control workflow. No shell evaluation or
// language runtime crosses the simulator/policy process boundary.
import "../host/json.flex";
global vc_env=0;
global vc_size=0;
global vc_sha=0;
global vc_rng=7;
global vc_copy_fn=0;
global vc_io_timeout=45000;
global VC_MAX_FILE_BYTES=2147483648;
fn vc_require(ok,message) {if !ok {pl_print(2,"Visual control: ");pl_print(2,message);pl_print(2,"\n");syscall(231,1,0,0,0,0,0);}return 0;}
fn vc_init(argc,argv) {vc_require(pl_init(),"host initialization failed");vc_env=argv+(argc+1)*8;vc_copy_fn=ffi_symbol(ffi_open("libc.so.6"),"memcpy");let timeout=pl_environment(argc,argv,"PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS");if timeout {let value=pl_integer(timeout,pl_size(timeout));vc_require(!pl_bad_number && value>=45000 && value<=600000,"local stream timeout must be 45000..600000 milliseconds");vc_io_timeout=value;}return 1;}
fn vc_copy(out,source,n) {ffi_call(vc_copy_fn,out,source,n,0,0,0);return out;}
fn vc_string(text) {let n=pl_size(text)+1;let out=alloc(n);vc_copy(out,text,n);return out;}
fn vc_concat(a,b) {let n=pl_size(a);let m=pl_size(b);let out=alloc(n+m+1);vc_copy(out,a,n);vc_copy(out+n,b,m+1);return out;}
fn vc_path(root,leaf) {if load8(leaf)==47 {return vc_string(leaf);}return vc_concat(vc_concat(root,"/"),leaf);}
fn vc_int(value) {let out=alloc(64);let b=alloc(32);pl_builder(b,out,64);pl_int(b,value);syscall(11,b,32,0,0,0,0);return out;}
fn vc_number(n,d) {return f64_div(f64_from_i64(n),f64_from_i64(d));}
fn vc_random() {vc_rng=(vc_rng*1103515245+12345)&2147483647;return vc_number(vc_rng,2147483648);}
fn vc_uniform(lo,hi) {return f64_add(lo,f64_mul(f64_sub(hi,lo),vc_random()));}
fn vc_absolute(path) {if load8(path)==47 {return vc_string(path);}let cwd=alloc(4096);vc_require(syscall(79,cwd,4096,0,0,0,0)>0,"cannot read working directory");return vc_path(cwd,path);}
fn vc_mkdir(path) {vc_require(!syscall(83,path,448,0,0,0,0),"output directory must be new, with an existing parent");return path;}
fn vc_map_bounded(path,limit) {
    let fd=syscall(2,path,0x80000,0,0,0,0);vc_require(fd>=0,vc_concat("cannot open ",path));
    vc_size=syscall(8,fd,0,2,0,0,0);if limit==VC_MAX_FILE_BYTES {vc_require(vc_size>=1 && vc_size<=limit,"file size is outside 1 B..2 GiB");}else {vc_require(vc_size>=1 && vc_size<=limit,"file size is outside the permitted range");}
    let data=syscall(9,0,vc_size,1,2,fd,0);syscall(3,fd,0,0,0,0,0);vc_require(data>0,"cannot map file");return data;
}
fn vc_map(path) {return vc_map_bounded(path,VC_MAX_FILE_BYTES);}
fn vc_map_highres(path) {let data=vc_map_bounded(path,8589934592);vc_require(vc_size>=32 && load64(data)==load64("PVDAT128"),"invalid high-resolution data file");return data;}
fn vc_text_file(path) {let data=vc_map(path);let n=vc_size;let out=alloc(n+1);vc_copy(out,data,n);syscall(11,data,n,0,0,0,0);return out;}
fn vc_write(path,data,size) {vc_require(!pl_atomic_file(path,data,size),vc_concat("cannot write ",path));return 0;}
fn vc_save_text(path,text) {return vc_write(path,text,pl_size(text));}
fn vc_copy_file(source,target) {let data=vc_map(source);let n=vc_size;vc_write(target,data,n);syscall(11,data,n,0,0,0,0);return 0;}
fn vc_digest(data,size) {
    if !vc_sha {vc_sha=ffi_symbol(ffi_open("libcrypto.so.3"),"SHA256");vc_require(vc_sha,"SHA256 is unavailable");}
    let digest=alloc(32);ffi_call(vc_sha,data,size,digest,0,0,0);let out=alloc(65);let hex="0123456789abcdef";let i=0;
    while i<32 {let value=load8(digest+i);store8(out+i*2,load8(hex+(value>>4)));store8(out+i*2+1,load8(hex+(value&15)));i=i+1;}syscall(11,digest,32,0,0,0,0);return out;
}
fn vc_file_sha(path) {let data=vc_map(path);let n=vc_size;let out=vc_digest(data,n);syscall(11,data,n,0,0,0,0);return out;}
fn vc_highres_file_sha(path) {let data=vc_map_highres(path);let n=vc_size;let out=vc_digest(data,n);syscall(11,data,n,0,0,0,0);return out;}
fn vc_json_file(path) {let text=vc_text_file(path);let root=pj_parse(text,pl_size(text));vc_require(root,pj_message);return root;}
fn vc_json_path(root,a,b) {let node=pj_get(root,a);if b {node=pj_get(node,b);}return node;}
fn vc_json_real(root,a,b) {let value=pj_real_node(vc_json_path(root,a,b));vc_require(!pj_error && f64_is_finite(value),"missing/invalid observation number");return value;}
fn vc_json_int(root,a,b) {let node=vc_json_path(root,a,b);vc_require(pj_kind(node)==1,"missing observation integer");return pj_value(node);}
fn vc_args() {return alloc(8+129*8);}
fn vc_add(args,text) {let n=load64(args);vc_require(n<128,"too many process arguments");store64(args+8+n*8,text);store64(args,n+1);store64(args+16+n*8,0);return text;}
fn vc_spawn(args,log_path,directory,channel) {
    let result=alloc(16);let parent=-1;let child=-1;let pair=alloc(8);
    if channel {vc_require(!syscall(53,1,0x80801,0,pair,0,0),"cannot create local stream");parent=pb_u32(pair);child=pb_u32(pair+4);}
    let log=syscall(2,log_path,0x800c1,384,0,0,0);vc_require(log>=0,"process log must be new");let owner=syscall(39,0,0,0,0,0,0);let pid=syscall(57,0,0,0,0,0,0);
    if !pid {
        syscall(157,1,9,0,0,0,0);if syscall(110,0,0,0,0,0,0)!=owner {syscall(60,125,0,0,0,0,0);}
        syscall(33,log,1,0,0,0,0);syscall(33,log,2,0,0,0,0);
        if channel {syscall(33,child,3,0,0,0,0);syscall(72,3,2,0,0,0,0);syscall(72,3,4,0,0,0,0);syscall(436,4,0xffffffff,0,0,0,0);}else {syscall(436,3,0xffffffff,0,0,0,0);}
        if directory && syscall(80,directory,0,0,0,0,0) {syscall(60,126,0,0,0,0,0);}
        syscall(59,load64(args+8),args+8,vc_env,0,0,0);syscall(60,127,0,0,0,0,0);
    }
    syscall(3,log,0,0,0,0,0);if channel {syscall(3,child,0,0,0,0,0);}vc_require(pid>0,"cannot fork process");store64(result,pid);store64(result+8,parent);return result;
}
fn vc_reap(process,timeout) {
    let status=alloc(8);let deadline=pl_now()+timeout;
    while 1 {let n=syscall(61,load64(process),status,1,0,0,0);if n==load64(process) {let result=pb_u32(status);store64(process,0);syscall(11,status,8,0,0,0,0);return result;}
        if n<0 && n!= -4 {return -1;}if pl_now()>=deadline {return -2;}syscall(7,0,0,2,0,0,0);}
    return -1;
}
fn vc_finish(process,timeout) {let fd=load64(process+8);if fd>=0 {syscall(3,fd,0,0,0,0,0);store64(process+8,-1);}let status=vc_reap(process,timeout);if status== -2 {syscall(62,load64(process),9,0,0,0,0);vc_reap(process,1000);}vc_require(!status,"child process failed or exceeded its time limit; inspect its log");return 0;}
fn vc_io(reading,fd,data,size) {
    let at=0;let deadline=pl_now()+vc_io_timeout;
    while at<size {let n=0;if reading {n=syscall(0,fd,data+at,size-at,0,0,0);}else {n=syscall(44,fd,data+at,size-at,16384,0,0);}
        if n>0 {at=at+n;}else if n== -11 {let event=4;if reading {event=1;}vc_require(pl_wait(fd,event,deadline),"local process stream timed out");}else if n!= -4 {vc_require(0,"local process stream closed; inspect its log");}}
    return 1;
}
fn vc_replace(text,before,after) {
    let n=pl_size(text);let m=pl_size(before);let k=pl_size(after);let out=alloc(n*2+k+4096);let at=0;let used=0;
    while at<n {if pl_starts(text+at,before) {vc_copy(out+used,after,k);used=used+k;at=at+m;}else {store8(out+used,load8(text+at));used=used+1;at=at+1;}}
    return out;
}
