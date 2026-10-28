// Aggregate chase rounds into one PVDATA04 file of fixed-length windows: every fitting window first, then every validation window.
// Each window after the first replays BURN unsupervised frames so the memory warms up; every original frame is supervised exactly once.
import "../../../flex/control/dataset.flex";
global VG_MAX_WINDOWS=8192;
fn vg_starts(starts,length,window,burn) {
    let n=0;let end=0;while end<length {let start=pb_max(0,end-burn);if start+window>length {start=length-window;}store64(starts+n*16,start);store64(starts+n*16+8,end);n=n+1;end=start+window;}return n;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc>=5 && argc<=36,"aggregate OUTPUT WINDOW BURN DATA_1 [... DATA_32]");
    let window=pl_integer(load64(argv+16),pl_size(load64(argv+16)));let burn=pl_integer(load64(argv+24),pl_size(load64(argv+24)));vc_require(!pl_bad_number && window>=8 && window<=512 && burn>=0 && burn<window,"invalid window or burn-in");
    let count=argc-4;let sources=alloc(count*8);let length=0;let episodes=0;let fitting=0;let source=0;
    while source<count {let data=vd_map(vc_absolute(load64(argv+32+source*8)));let bytes=vc_size;let n=load64(data+8);let fit=load64(data+16);let t=load64(data+24);
        vc_require(vd_row_bytes(data)==44 && n>=2 && fit>=1 && fit<n && t>=window && t<=512 && bytes==32+n*t*21212 && (!length || t==length),"invalid or mismatched chase dataset");
        store64(sources+source*8,data);length=t;episodes=episodes+n;fitting=fitting+fit;source=source+1;}
    let starts=alloc(length*16);let per=vg_starts(starts,length,window,burn);let total=episodes*per;let size=32+total*window*21224;vc_require(total<=VG_MAX_WINDOWS && size<=8589934592,"aggregate exceeds limits");
    let output=vc_absolute(load64(argv+8));vc_mkdir(output);let partial=vc_path(output,"data.partial.bin");let fd=syscall(2,partial,0x800c2,384,0,0,0);vc_require(fd>=0 && !syscall(77,fd,size,0,0,0,0),"cannot allocate aggregate data");
    let merged=syscall(9,0,size,3,1,fd,0);vc_require(merged>0,"cannot map aggregate data");vc_copy(merged,"PVDATA04",8);store64(merged+8,total);store64(merged+16,fitting*per);store64(merged+24,window);
    let split=0;let target=0;while split<2 {source=0;while source<count {let data=load64(sources+source*8);let i=0;let end=load64(data+16);if split {i=end;end=load64(data+8);}
        while i<end {let from=data+32+i*length*21212;let k=0;while k<per {let start=load64(starts+k*16);let first=load64(starts+k*16+8);let to=merged+32+target*window*21224;vc_copy(to,from+start*21168,window*21168);
                let t=0;while t<window {let row=from+length*21168+(start+t)*44;let out=to+window*21168+t*56;vc_copy(out,row,44);if start+t<first {pb_put32(out+40,0);}pb_put32(out+44,0x3f800000);vc_copy(out+48,row+28,8);t=t+1;}
                target=target+1;k=k+1;}i=i+1;}
        source=source+1;}split=split+1;}
    vc_require(target==total,"missing aggregate windows");vc_require(!syscall(26,merged,size,4,0,0,0) && !syscall(74,fd,0,0,0,0,0),"cannot synchronize aggregate data");let checksum=vc_digest(merged,size);syscall(11,merged,size,0,0,0,0);syscall(3,fd,0,0,0,0,0);
    vc_require(!syscall(82,partial,vc_path(output,"data.bin"),0,0,0,0),"cannot publish aggregate data");
    let text=alloc(4096);let b=alloc(32);pl_builder(b,text,4096);pl_text(b,"{\"runtime\":\"Flexscript\",\"sourceGames\":");pl_int(b,episodes);pl_text(b,",\"fitGames\":");pl_int(b,fitting);pl_text(b,",\"windowsPerGame\":");pl_int(b,per);
    pl_text(b,",\"window\":");pl_int(b,window);pl_text(b,",\"burnIn\":");pl_int(b,burn);pl_text(b,",\"episodes\":");pl_int(b,total);pl_text(b,",\"dataSHA256\":");pj_text(b,checksum);pl_text(b,"}\n");vc_require(!load64(b+24),"aggregate receipt exceeded capacity");vc_write(vc_path(output,"report.json"),text,load64(b+8));return 0;
}
