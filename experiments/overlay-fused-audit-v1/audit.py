#!/usr/bin/env python3
"""Standalone fused stream proof; never use as the active overlay verifier."""
import hashlib
import math
import os
import stat
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Format:
    horizon: int
    image: int
    map_width: int

    @property
    def old_width(self):return self.image+44

    @property
    def new_width(self):return self.image+56


PRODUCTION=Format(horizon=300,image=21168,map_width=144)
HEADER=struct.Struct('<8sqqq')


def signature(info):
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_mode,info.st_uid,info.st_gid,info.st_nlink)


def open_regular(path):
    path=Path(path).absolute();before=os.lstat(path)
    if not stat.S_ISREG(before.st_mode):raise ValueError('input is not a regular non-symlink file')
    fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        opened=os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or signature(opened)!=signature(before):raise ValueError('input changed during open')
        return path,fd,signature(opened)
    except BaseException:
        os.close(fd);raise


def stable(path,fd,pinned):
    try:current=os.lstat(path);opened=os.fstat(fd)
    except OSError as error:raise ValueError('input disappeared') from error
    if not stat.S_ISREG(current.st_mode) or signature(current)!=pinned or signature(opened)!=pinned:raise ValueError('input changed or path was replaced')


def expected_sha(value):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('invalid expected SHA-256')
    return value


def complete_digest(fd):
    digest=hashlib.sha256();offset=0
    while True:
        data=os.pread(fd,1024*1024,offset)
        if not data:break
        digest.update(data);offset+=len(data)
    return digest.hexdigest(),offset


def read_exact(fd,offset,size):
    data=os.pread(fd,size,offset)
    if len(data)!=size:raise ValueError('truncated input')
    return data


def parse_header(raw,magic,fmt,width,filesize):
    if len(raw)!=HEADER.size:raise ValueError('truncated header')
    got,n,fit,horizon=HEADER.unpack(raw)
    if got!=magic or not 2<=n<=1024 or not 1<=fit<n or horizon!=fmt.horizon or filesize!=HEADER.size+n*horizon*width:raise ValueError('invalid header or file size')
    return n,fit


def converted_student(fd,episode,fmt):
    start=HEADER.size+episode*fmt.horizon*fmt.old_width;images_size=fmt.horizon*fmt.image
    images=read_exact(fd,start,images_size);rows=read_exact(fd,start+images_size,fmt.horizon*44)
    result=bytearray(fmt.horizon*fmt.new_width);result[:images_size]=images
    for i in range(fmt.horizon):
        old=rows[i*44:(i+1)*44];position=images_size+i*56
        steer,speed,weight=struct.unpack_from('<2f4xf',old,28)
        if not all(math.isfinite(x) and abs(x)<=1 for x in (steer,speed)) or weight!=1:raise ValueError('invalid student label')
        result[position:position+44]=old;result[position+44:position+48]=struct.pack('<f',1);result[position+48:position+56]=old[28:36]
    return bytes(result)


def audit(base,stage,mapping,expected_base,expected_stage,source_hashes,*,kind,fmt=PRODUCTION,_hook=None):
    """Compare one aggregate file and full SHA pins; all paths are read-only.

    mapping maps destination index to (source file path, episode). source_hashes
    provides an expected full SHA for every source file and no extras. The
    optional hook is solely for deterministic synthetic fault injection.
    """
    if kind not in ('data','map') or not isinstance(fmt,Format) or any(type(x) is not int or x<=0 for x in (fmt.horizon,fmt.image,fmt.map_width)):raise ValueError('invalid format')
    expected_base=expected_sha(expected_base);expected_stage=expected_sha(expected_stage)
    if not isinstance(mapping,dict) or not isinstance(source_hashes,dict):raise ValueError('invalid mapping or source pins')
    normalized={}
    for index,value in mapping.items():
        if type(index) is not int or not isinstance(value,tuple) or len(value)!=2 or type(value[1]) is not int or value[1]<0:raise ValueError('invalid slot mapping')
        normalized[index]=(Path(value[0]).absolute(),value[1])
    pins={Path(p).absolute():expected_sha(digest) for p,digest in source_hashes.items()}
    if len(pins)!=len(source_hashes) or set(pins)!={p for p,_ in normalized.values()}:raise ValueError('source pin inventory differs')
    records=[]
    def checkpoint(label,index=None):
        if _hook is not None:_hook(label,index)
    def add(path):
        item=open_regular(path);records.append(item);return item
    try:
        old=add(base);new=add(stage);sources={p:add(p) for p in sorted(pins)}
        if len({(s[2][0],s[2][1]) for s in records})!=len(records):raise ValueError('input files share an inode')
        width=fmt.new_width if kind=='data' else fmt.map_width;magic=b'PVDATA04' if kind=='data' else b'PVMAP001'
        old_header=read_exact(old[1],0,HEADER.size);new_header=read_exact(new[1],0,HEADER.size)
        dims=parse_header(old_header,magic,fmt,width,old[2][2])
        if parse_header(new_header,magic,fmt,width,new[2][2])!=dims or old_header!=new_header:raise ValueError('aggregate headers differ')
        n,_=dims
        if any(not 0<=index<n for index in normalized):raise ValueError('slot outside aggregate')
        source_dims={};source_reads=0
        for path,item in sources.items():
            magic_source=b'PVDATA01' if kind=='data' else b'PVMAP001';source_width=fmt.old_width if kind=='data' else fmt.map_width
            source_dims[path]=parse_header(read_exact(item[1],0,HEADER.size),magic_source,fmt,source_width,item[2][2])
            digest,count=complete_digest(item[1]);source_reads+=count
            if digest!=pins[path] or count!=item[2][2]:raise ValueError('source pre-pass digest differs')
            stable(*item)
        if any(episode>=source_dims[path][0] for path,episode in normalized.values()):raise ValueError('source episode outside shard')
        checkpoint('after_source_prepass')
        old_hash=hashlib.sha256(old_header);new_hash=hashlib.sha256(new_header);total=HEADER.size;chunk=fmt.horizon*width
        for index in range(n):
            a=read_exact(old[1],HEADER.size+index*chunk,chunk);b=read_exact(new[1],HEADER.size+index*chunk,chunk)
            old_hash.update(a);new_hash.update(b);total+=chunk
            if index not in normalized:
                if a!=b:raise ValueError('unchanged game differs')
            else:
                path,episode=normalized[index];fd=sources[path][1]
                expected=converted_student(fd,episode,fmt) if kind=='data' else read_exact(fd,HEADER.size+episode*chunk,chunk)
                if b!=expected:raise ValueError('replaced game differs')
            checkpoint('after_game',index)
        if total!=old[2][2] or total!=new[2][2] or old_hash.hexdigest()!=expected_base or new_hash.hexdigest()!=expected_stage:raise ValueError('fused aggregate digest differs')
        for item in records:stable(*item)
        checkpoint('before_postpass')
        old_post,old_count=complete_digest(old[1]);new_post,new_count=complete_digest(new[1])
        if old_count!=total or new_count!=total or old_post!=expected_base or new_post!=expected_stage:raise ValueError('aggregate post-pass digest differs')
        for path,item in sources.items():
            digest,count=complete_digest(item[1]);source_reads+=count
            if digest!=pins[path] or count!=item[2][2]:raise ValueError('source post-pass digest differs')
        for item in records:stable(*item)
        return {'status':'synthetic_diagnostic_only','baseSHA256':old_hash.hexdigest(),'stageSHA256':new_hash.hexdigest(),
                'fusedAggregateBytes':2*total,'postAggregateBytes':old_count+new_count,'sourceDigestBytes':source_reads,
                'scope':'exact recorded byte comparisons on pinned descriptors; first digest is accepted after the semantic stream; not hostile-owner or execution attestation'}
    finally:
        for _,fd,_ in reversed(records):os.close(fd)


if __name__=='__main__':raise SystemExit('Proof of concept only; no production CLI or integration.')
