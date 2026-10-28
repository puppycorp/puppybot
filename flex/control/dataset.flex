// Preserve complete demonstration histories while removing trailing padding.
import "host.flex";
fn vd_row_bytes(data) {if load64(data)==load64("PVDATA01") {return 44;}if load64(data)==load64("PVDATA02") {return 48;}if load64(data)==load64("PVDATA03") || load64(data)==load64("PVDATA04") {return 56;}return 0;}
fn vd_episode_limit(data) {if load64(data)==load64("PVDATA04") {return 1024;}return 256;}
// Larger files require a new magic. Legacy data retains its 2 GiB limit.
fn vd_map(path) {let data=vc_map_bounded(path,8589934592);vc_require(vc_size<=VC_MAX_FILE_BYTES || (vc_size>=32 && load64(data)==load64("PVDATA04")),"legacy demonstration data exceeds 2 GiB");return data;}
fn vd_file_sha(path) {let data=vd_map(path);let bytes=vc_size;let checksum=vc_digest(data,bytes);syscall(11,data,bytes,0,0,0,0);return checksum;}
fn vd_copy_file(source,target) {let data=vd_map(source);let bytes=vc_size;vc_write(target,data,bytes);syscall(11,data,bytes,0,0,0,0);return 0;}
fn vd_valid_word(row,bytes) {if bytes>=48 {return pb_u32(row+44);}return pb_u32(row+40);}
fn vd_pack(path,output) {
    let data=vc_map(path);let bytes=vc_size;vc_require(bytes>=32,"invalid demonstration dataset");let row_bytes=vd_row_bytes(data);vc_require(row_bytes,"invalid demonstration dataset");let episodes=load64(data+8);let fit=load64(data+16);let length=load64(data+24);
    vc_require(episodes>=2 && episodes<=256 && fit>=1 && fit<episodes && length>=1 && length<=512 && bytes==32+episodes*length*(21168+row_bytes),"invalid demonstration dimensions");let longest=0;let valid=0;let supervised=0;let episode=0;
    while episode<episodes {let base=data+32+episode*length*(21168+row_bytes);let t=0;let padded=0;let count=0;let labels=0;
        while t<length {let row=base+length*21168+t*row_bytes;let field=0;while field<row_bytes/4 {vc_require(f64_is_finite(pb_read_float(row+field*4)),"nonfinite demonstration value");field=field+1;}
            vc_require(!pb_u32(row+24),"task-event feedback must be masked during packing");vc_require(f64_le(f64_magnitude(pb_read_float(row+28)),PB_ONE) && f64_le(f64_magnitude(pb_read_float(row+32)),PB_ONE),"demonstration action exceeds [-1,1]");
            vc_require((pb_u32(row+36)==0 || pb_u32(row+36)==0x3f800000) && (pb_u32(row+40)==0 || pb_u32(row+40)==0x3f800000),"invalid demonstration phase/mask");
            let frame=vd_valid_word(row,row_bytes);vc_require(frame==0 || frame==0x3f800000,"invalid valid-frame mask");vc_require(!pb_u32(row+40) || frame,"supervised padding frame");
            if row_bytes==56 {vc_require(f64_le(f64_magnitude(pb_read_float(row+48)),PB_ONE) && f64_le(f64_magnitude(pb_read_float(row+52)),PB_ONE),"executed demonstration action exceeds [-1,1]");}
            if frame {vc_require(!padded,"valid-frame mask has an internal gap");count=count+1;if pb_u32(row+40) {labels=labels+1;}else {vc_require(!labels,"supervision mask has an internal gap");}}else {padded=1;let i=0;while i<row_bytes {vc_require(!load8(row+i),"nonzero padding feedback/target");i=i+1;}i=0;while i<21168 {vc_require(!load8(base+t*21168+i),"nonzero padding image");i=i+1;}}t=t+1;
        }vc_require(count>=1 && labels>=1,"empty demonstration or supervised episode");longest=pb_max(longest,count);valid=valid+count;supervised=supervised+labels;episode=episode+1;
    }
    vc_mkdir(output);let size=32+episodes*longest*(21168+row_bytes);let packed=alloc(size);vc_copy(packed,data,32);store64(packed+24,longest);episode=0;
    while episode<episodes {let source=data+32+episode*length*(21168+row_bytes);let target=packed+32+episode*longest*(21168+row_bytes);vc_copy(target,source,longest*21168);vc_copy(target+longest*21168,source+length*21168,longest*row_bytes);episode=episode+1;}
    let target=vc_path(output,"data.bin");vc_write(target,packed,size);let out=alloc(2048);let b=alloc(32);pl_builder(b,out,2048);pl_text(b,"{\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"episodes\":");pl_int(b,episodes);pl_text(b,",\"validSteps\":");pl_int(b,valid);pl_text(b,",\"originalSequenceLength\":");pl_int(b,length);pl_text(b,",\"sequenceLength\":");pl_int(b,longest);
    pl_text(b,",\"supervisedSteps\":");pl_int(b,supervised);pl_text(b,",\"completeHistoriesPreserved\":true,\"onlyTrailingPaddingRemoved\":true,\"sourceSHA256\":");pj_text(b,vc_digest(data,bytes));pl_text(b,",\"dataSHA256\":");pj_text(b,vc_digest(packed,size));pl_text(b,"}\n");vc_require(!load64(b+24),"packed dataset receipt exceeded capacity");vc_write(vc_path(output,"report.json"),out,load64(b+8));pl_write(1,out,load64(b+8));syscall(11,data,bytes,0,0,0,0);syscall(11,packed,size,0,0,0,0);return 0;
}
