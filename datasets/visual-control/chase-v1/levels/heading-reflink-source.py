#!/usr/bin/env python3
"""Source-only prototype: require Btrfs FICLONE for trainer data copies.

The unchanged worktree source is not edited. Both experimental training arms
must use the same isolated rebuilt control binary. Failure to clone leaves a
new partial output, and never falls back to a full copy or removes a file.
"""


COPY = 'fn vd_copy_file(source,target) {let data=vd_map(source);let bytes=vc_size;vc_write(target,data,bytes);syscall(11,data,bytes,0,0,0,0);return 0;}'
CLONE = '''fn vd_copy_file(source,target) {
    let src=syscall(2,source,0xa0000,0,0,0,0);vc_require(src>=0,"cannot open reflink source without following symlinks");
    let initial=alloc(144);let later=alloc(144);let named=alloc(144);vc_require(!syscall(5,src,initial,0,0,0,0),"cannot stat reflink source");
    vc_require((pb_u32(initial+24)&0xf000)==0x8000,"reflink source must be a regular file");
    let fdpath=vc_concat("/proc/self/fd/",vc_int(src));let expected=vd_file_sha(fdpath);
    let dst=syscall(2,target,0x800c2,384,0,0,0);vc_require(dst>=0,"reflink target must be new");
    vc_require(!syscall(16,dst,0x40049409,src,0,0,0),"FICLONE failed; partial target retained; full copy disabled");
    vc_require(!syscall(74,dst,0,0,0,0,0),"cannot synchronize reflink");
    let dest_initial=alloc(144);let dest_later=alloc(144);let dest_named=alloc(144);vc_require(!syscall(5,dst,dest_initial,0,0,0,0),"cannot stat reflink target");
    vc_require((pb_u32(dest_initial+24)&0xf000)==0x8000 && load64(dest_initial+48)==load64(initial+48),"invalid reflink target");
    vc_require(!syscall(5,src,later,0,0,0,0) && !syscall(6,source,named,0,0,0,0),"cannot recheck reflink identity");
    vc_require(load64(initial)==load64(later) && load64(initial+8)==load64(later+8) && load64(initial+48)==load64(later+48) && load64(initial+88)==load64(later+88) && load64(initial+96)==load64(later+96) && load64(initial+104)==load64(later+104) && load64(initial+112)==load64(later+112),"reflink source changed");
    vc_require((pb_u32(named+24)&0xf000)==0x8000 && load64(initial)==load64(named) && load64(initial+8)==load64(named+8),"reflink source path changed");
    let dstpath=vc_concat("/proc/self/fd/",vc_int(dst));vc_require(pl_equal(expected,vd_file_sha(fdpath)) && pl_equal(expected,vd_file_sha(dstpath)),"reflink data hash differs");
    vc_require(!syscall(5,src,later,0,0,0,0) && load64(initial)==load64(later) && load64(initial+8)==load64(later+8) && load64(initial+48)==load64(later+48) && load64(initial+88)==load64(later+88) && load64(initial+96)==load64(later+96) && load64(initial+104)==load64(later+104) && load64(initial+112)==load64(later+112),"reflink source changed after hashing");
    vc_require(!syscall(6,source,named,0,0,0,0) && (pb_u32(named+24)&0xf000)==0x8000 && load64(initial)==load64(named) && load64(initial+8)==load64(named+8),"reflink source path changed after hashing");
    vc_require(!syscall(5,dst,dest_later,0,0,0,0) && !syscall(6,target,dest_named,0,0,0,0),"cannot recheck reflink target identity");
    vc_require(load64(dest_initial)==load64(dest_later) && load64(dest_initial+8)==load64(dest_later+8) && load64(dest_initial+48)==load64(dest_later+48) && load64(dest_initial+88)==load64(dest_later+88) && load64(dest_initial+96)==load64(dest_later+96) && load64(dest_initial+104)==load64(dest_later+104) && load64(dest_initial+112)==load64(dest_later+112),"reflink target changed during hashing");
    vc_require((pb_u32(dest_named+24)&0xf000)==0x8000 && load64(dest_initial)==load64(dest_named) && load64(dest_initial+8)==load64(dest_named+8),"reflink target path changed");
    let cut=pl_size(target);while cut && load8(target+cut-1)!=47 {cut=cut-1;}vc_require(cut,"reflink target needs parent path");let parent=alloc(cut+1);vc_copy(parent,target,cut);store8(parent+cut,0);
    let directory=syscall(2,parent,0x90000,0,0,0,0);vc_require(directory>=0 && !syscall(74,directory,0,0,0,0,0),"cannot synchronize reflink directory");
    syscall(3,directory,0,0,0,0,0);syscall(3,dst,0,0,0,0,0);syscall(3,src,0,0,0,0,0);return 0;
}'''


def transform(text):
    if text.count(COPY) != 1:
        raise ValueError('unexpected dataset source; refusing transformation')
    return text.replace(COPY, CLONE, 1)
