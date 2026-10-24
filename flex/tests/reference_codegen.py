"""Shape specialization, fusion and register/shared-memory tiling for static Pup IR.

The input is the native graph inventory, independent of model names and weights.
Generated Flexscript passes through the normal word IR and GPU machine backends.
"""
import argparse
import ast
from collections import defaultdict
import hashlib
import json
import math
import re
from pathlib import Path
import struct
import subprocess

from flex.tests.indexing import DECLARATIONS, narrow
from flex.tests import tensorcore

ROOT = Path(__file__).resolve().parents[2]
TARGETS = {'sass': ('sass-sm75', 'cubin'), 'cuda': ('ptx', 'ptx'), 'hip': ('hip', 'hip')}


def quotient(value, divisor):
    """Exact nonnegative division for the runtime's index domain [0,2^24)."""
    assert 0 < divisor <= 2**24
    if divisor == 1:
        return f'({value})'
    if divisor & (divisor-1) == 0:
        return f'(({value})>>{divisor.bit_length()-1})'
    return f'q{divisor}({value})'



def remainder(value, divisor):
    if divisor & (divisor-1) == 0:
        return f'(({value})&{divisor-1})'
    return f'(({value})-{quotient(value,divisor)}*{divisor})'


def broadcast(index, shape, source):
    stride = 1
    terms = []
    for dimension, other in reversed(list(zip(shape,source))):
        if other != 1:
            terms.append(f'{remainder(index,dimension)}*{stride}')
        index = quotient(index,dimension)
        stride *= other
    if shape == source:
        return 'index'
    return '+'.join(terms) or '0'


def activation(value):
    return f'vk_mul({value},vk_sigmoid({value}))'


def shared_pitch(rows, reduction, vector=False):
    pitch=rows
    banks=1
    while banks*reduction<32: banks*=2
    if vector: banks=max(2,banks)
    while math.gcd(pitch,32)!=banks: pitch+=1
    return pitch


def tiled(node, silu=False, im2col=False, tile=None, vector=True, staging=4, streaming=True, batch_epilogue=True, pipeline=True, patch_tiles=False, unroll=0, packed_masks=False):
    op, shape, a, b, params, has_bias = node['op'],node['shape'],node['a'],node['b'],node['params'],node['bias']
    if op == 12:
        k,stride,pad,groups = params
        batch,cin,ih,iw = a
        _,cout,oh,ow = shape
        m,n,reduction = cout//groups,oh*ow,cin//groups*k*k
        batches = batch*groups
    else:
        m,n,reduction = shape[-2],shape[-1],a[-1]
        batches = math.prod(shape[:-2]); groups = 1
    tm,tn,tk = 32,64,32
    rm,rn = 4,4
    def blocks(): return batches*((m+tm-1)//tm)*((n+tn-1)//tn)
    if m <= 16: tm,rm = 16,2
    if blocks()<72: tn=32
    if blocks()<72: tm,rm=16,2
    if blocks()<72: tn,rn=16,2
    if blocks()<36: tm,rm=8,1
    if patch_tiles and op==12 and k==3:
        if m<=8: tm,rm=8,1
        if m%tm==0: tk=18 if reduction%18==0 else 9
    if tile is not None: tm,tn,tk,rm,rn=tile
    # A transposed tile needs a padded pitch so adjacent K lanes do not all
    # store to the same shared-memory bank.
    pitch_a=shared_pitch(tm,tk,vector and rm%2==0)
    size_a=pitch_a*tk
    threads = tm//rm*(tn//rn)
    mb,nb = (m+tm-1)//tm,(n+tn-1)//tn
    vector_b=vector and rn%2==0 and size_a%2==0
    swizzle=vector_b and rn>=4 and tn>=64
    swizzle_mask=min(rn//2-1,tn//32-1) if swizzle else 0
    def column(value): return f'(({value})^((({value})>>5)&{swizzle_mask})*2)' if swizzle else value
    code = [f'let tid=gpu_thread_x();let block=gpu_block_x();let bn={remainder("block",nb)}*{tn};let bm={remainder(quotient("block",nb),mb)}*{tm};let batch={quotient("block",nb*mb)};',
            f'let mr={quotient("tid",tn//rn)}*{rm};let nr={remainder("tid",tn//rn)};',
            'let weights=gpu_launch_word(1);let bias=gpu_launch_word(2);let other=gpu_launch_word(0);let mrb=mr*4;let nrb=nr*4;']
    if vector_b:
        code += [f'nr=nr*{rn};']
        code += [f'let nrb{j}={column(f"(nr+{j})")}*4;' for j in range(0,rn,2)]
    code += [f'let c{i}{j}=0;' for i in range(rm) for j in range(rn)]
    scratch=threads if staging and (tm*tk%threads%32 or tk*tn%threads%32) else 0
    full_a = m%tm==0 and reduction%tk==0
    full_b = n%tn==0 and reduction%tk==0
    streamed=streaming and staging and full_a and threads>=tk and threads>=tn and threads%tk==0 and tm*tk%threads==0 and tk*tn%threads==0 and (op==29 or im2col or (op==12 and k==1 and stride==1 and pad==0))
    if streamed:
        row=f'(bm+{quotient("tid",tk)})'
        a_index=f'(({remainder("batch",groups)}*{m}+{row})*{reduction}+{remainder("tid",tk)})' if op==12 else f'((batch*{m}+{row})*{reduction}+{remainder("tid",tk)})'
        code += [f'let col=bn+{remainder("tid",tn)};let column_mask=0-(col<{n});let safe_col=col*(col<{n});',
                 f'let a_base={"weights" if op==12 else "input"}+{a_index}*4;',
                 f'let b_base={"other" if op==29 or im2col else "input"}+((batch*{reduction}+{quotient("tid",tn)})*{n}+safe_col)*4;',
                 f'let shared_a=({remainder("tid",tk)}*{pitch_a}+{quotient("tid",tk)})*4;let shared_b=({size_a}+{column("tid") if swizzle else "tid"})*4;']
    cached=staging and op==12 and k==3 and not im2col and full_a and tk%9==0 and threads%tn==0
    if cached:
        code += ['let a_base=weights;',f'let b_base=input+({quotient("batch",groups)}*{cin}+{remainder("batch",groups)}*{cin//groups})*{ih*iw*4};']
        code += [f'let shared_b=({size_a}+{column("tid") if swizzle else "tid"})*4;']
        for step in range((tm*tk+threads-1)//threads):
            code += [f'let v=tid+{step*threads};let ar={quotient("v",tk)};let ak=v-ar*{tk};',
                     f'let weight_entry{step}=(({remainder("batch",groups)}*{m}+bm+ar)*{reduction}+ak)|(((ak*{pitch_a}+ar)*4)<<32);']
        code += [f'let col=bn+{remainder("tid",tn)};let oy={quotient("col",ow)};let ox=col-oy*{ow};oy=oy*{stride}-{pad};ox=ox*{stride}-{pad};',
                 f'let column_valid={"1" if n%tn==0 else f"col<{n}"};let lane_k={quotient("tid",tn)};']
        lanes=threads//tn
        def lookup(values,fallback):
            if len(set(values))==1: return str(values[0])
            delta=values[1]-values[0]
            if all(v==values[0]+i*delta for i,v in enumerate(values)):
                return f'({values[0]}+lane_k*{delta})' if delta>=0 else f'({values[-1]}+({lanes-1}-lane_k)*{-delta})'
            bits=max(1,max(values).bit_length())
            if bits*len(values)>64: return fallback
            packed=sum(value<<(i*bits) for i,value in enumerate(values))
            return f'((0x{packed:x}>>(lane_k*{bits}))&{(1<<bits)-1})'
        for step in range(min(9,(tk*tn+threads-1)//threads)):
            plane=f'(lane_k+{step*lanes})';planes=range(step*lanes,(step+1)*lanes)
            channel=lookup([v//9 for v in planes],quotient(plane,9))
            ky=lookup([v//3%3 for v in planes],remainder(quotient(plane,3),3))
            kx=lookup([v%3 for v in planes],remainder(plane,3))
            mask='((0-valid)<<32)' if packed_masks else '(valid<<31)'
            code += [f'let iy=oy+{ky};let ix=ox+{kx};let valid=column_valid*(iy>=0)*(iy<{ih})*(ix>=0)*(ix<{iw});',
                     f'let image_lookup{step}=(({channel}*{ih*iw}+iy*{iw}+ix)*valid)|{mask};']
    if staging:
        def load(stage,slot,step):
            size=tm*tk if stage=='a' else tk*tn
            limit=size-step*threads
            partial=limit<threads and limit%32!=0
            active=f'(tid<{limit})' if partial else '1'
            def finish(c):
                if partial:
                    c += [f'shared{slot}=shared{slot}*{active}+({size_a+tk*tn}+tid)*4*(1-{active});mask{slot}=mask{slot}*{active};']
                return c
            if cached:
                v=f'(tid+{step*threads})'
                if stage=='a':
                    return finish([f'let shared{slot}=weight_entry{step}>>32;let mask{slot}=-1;let staged{slot}=gpu_load_u32(gpu_address_f32(a_base,weight_entry{step}*{active}));'])
                if packed_masks:
                    return finish([f'let shared{slot}=shared_b+{step*threads*4};let mask{slot}=image_lookup{step%9}>>32;let staged{slot}=gpu_load_u32(gpu_address_f32(b_base,(image_lookup{step%9}+{step//9*(threads//tn)*ih*iw})*{active}));'])
                return finish([f'let shared{slot}=shared_b+{step*threads*4};let mask{slot}=0-((image_lookup{step%9}>>31)&1);let staged{slot}=gpu_load_u32(b_base+(((image_lookup{step%9}&0x7fffffff)+{step//9*(threads//tn)*ih*iw})*{active})*4);'])

            if streamed:
                byte_stride=(threads//tk*reduction if stage=='a' else threads//tn*n)*4
                shared_step=threads//tk*4 if stage=='a' else threads*4
                mask='-1' if stage=='a' or full_b else 'column_mask'
                return [f'let shared{slot}=shared_{stage}+{step*shared_step};let mask{slot}={mask};let staged{slot}=gpu_load_u32({stage}_base+{step*byte_stride});']
            c=[f'let v=tid+{step*threads};']
            if stage=='a':
                c += [f'let row=bm+{quotient("v",tk)};let kk=base+{remainder("v",tk)};',f'let valid={"1" if full_a else f"(row<{m})*(kk<{reduction})"};']
                address=f'(({remainder("batch",groups)}*{m}+row)*{reduction}+kk)' if op==12 else f'((batch*{m}+row)*{reduction}+kk)'
                source='weights' if op==12 else 'input'
                shared=f'({remainder("v",tk)}*{pitch_a}+{quotient("v",tk)})*4'
            else:
                c += [f'let col=bn+{remainder("v",tn)};let kk=base+{quotient("v",tn)};',f'let valid={"1" if full_b else f"(col<{n})*(kk<{reduction})"};']
                source='input'
                if op==12 and im2col:
                    address=f'((batch*{reduction}+kk)*{n}+col)';source='other'
                elif op==12 and k==1 and stride==1 and pad==0:
                    address=f'(({quotient("batch",groups)}*{cin}+{remainder("batch",groups)}*{cin//groups}+kk)*{n}+col)'
                elif op==12:
                    c += [f'let iy={quotient("col",ow)}*{stride}+{remainder(quotient("kk",k),k)}-{pad};let ix={remainder("col",ow)}*{stride}+{remainder("kk",k)}-{pad};valid=valid*(iy>=0)*(iy<{ih})*(ix>=0)*(ix<{iw});']
                    address=f'((({quotient("batch",groups)}*{cin}+{remainder("batch",groups)}*{cin//groups}+{quotient("kk",k*k)})*{ih}+iy)*{iw}+ix)'
                else:
                    address=f'((batch*{reduction}+kk)*{n}+col)';source='other'
                shared=f'({size_a}+{column("v") if swizzle else "v"})*4'
            if partial: c += [f'valid=valid*{active};']
            c += [f'let address={address}*valid;let shared{slot}={shared};let mask{slot}=0-valid;let staged{slot}=gpu_load_u32({source}+address*4);']
            return finish(c)
        code += ['let base=0;',f'while base<{reduction} {{']
        for stage,size in (('a',tm*tk),('b',tk*tn)):
            steps=(size+threads-1)//threads
            for start in range(0,steps,staging):
                count=min(staging,steps-start)
                for slot in range(count):
                    limit=size-(start+slot)*threads
                    uniform=limit<threads and limit%32==0
                    if uniform: code += [f'if tid<{limit} {{']
                    code += load(stage,slot,start+slot)
                    if uniform: code += ['}']
                for slot in range(count):
                    limit=size-(start+slot)*threads
                    uniform=limit<threads and limit%32==0
                    if uniform: code += [f'if tid<{limit} {{']
                    code += [f'gpu_shared_store_u32(shared{slot},staged{slot}&mask{slot});']
                    if uniform: code += ['}']
        code += ['gpu_shared_barrier();']
    else:
        code += ['let base=0;', f'while base<{reduction} {{', 'let v=tid;',f'while v<{tm*tk} {{',
                 f'let row=bm+{quotient("v",tk)};let kk=base+{remainder("v",tk)};',f'let valid={"1" if full_a else f"(row<{m})*(kk<{reduction})"};']
        if op == 12:
            code += [f'let address=(({remainder("batch",groups)}*{m}+row)*{reduction}+kk)*valid;let value=gpu_load_u32(weights+address*4)&(0-valid);']
        else:
            code += [f'let address=((batch*{m}+row)*{reduction}+kk)*valid;let value=gpu_load_u32(input+address*4)&(0-valid);']
        code += [f'gpu_shared_store_u32(({remainder("v",tk)}*{pitch_a}+{quotient("v",tk)})*4,value);v=v+{threads};', '}',
                 'v=tid;',f'while v<{tk*tn} {{', f'let col=bn+{remainder("v",tn)};let kk=base+{quotient("v",tn)};let valid={"1" if full_b else f"(col<{n})*(kk<{reduction})"};']
        if op == 12 and im2col:
            code += [f'let address=((batch*{reduction}+kk)*{n}+col)*valid;let value=gpu_load_u32(other+address*4)&(0-valid);']
        elif op == 12 and k==1 and stride==1 and pad==0:
            code += [f'let address=(({quotient("batch",groups)}*{cin}+{remainder("batch",groups)}*{cin//groups}+kk)*{n}+col)*valid;let value=gpu_load_u32(input+address*4)&(0-valid);']
        elif op == 12:
            code += [f'let iy={quotient("col",ow)}*{stride}+{remainder(quotient("kk",k),k)}-{pad};',
                     f'let ix={remainder("col",ow)}*{stride}+{remainder("kk",k)}-{pad};',
                     f'valid=valid*(iy>=0)*(iy<{ih})*(ix>=0)*(ix<{iw});let address=((({quotient("batch",groups)}*{cin}+{remainder("batch",groups)}*{cin//groups}+{quotient("kk",k*k)})*{ih}+iy)*{iw}+ix)*valid;let value=gpu_load_u32(input+address*4)&(0-valid);']
        else:
            code += [f'let address=((batch*{reduction}+kk)*{n}+col)*valid;let value=gpu_load_u32(other+address*4)&(0-valid);']
        shared_v=column('v') if swizzle else 'v'
        code += [f'gpu_shared_store_u32(({size_a}+{shared_v})*4,value);v=v+{threads};', '}',
                 'gpu_shared_barrier();']
    def operands(kk, suffix):
        loads=[]
        for i in range(rm):
            if vector and rm%2==0 and i%2: continue
            value=f'w{i-1}{suffix}>>32' if vector and rm%2==0 and i%2 else f'gpu_shared_load64(mrb+{(kk*pitch_a+i)*4})' if vector and rm%2==0 else f'gpu_shared_load_u32(mrb+{(kk*pitch_a+i)*4})'
            loads += [f'let w{i}{suffix}={value};']
        for j in range(rn):
            if vector_b and j%2: continue
            value=f'x{j-1}{suffix}>>32' if vector_b and j%2 else f'gpu_shared_load64(nrb{j}+{(size_a+kk*tn)*4})' if vector_b else f'gpu_shared_load_u32(nrb+{(size_a+kk*tn+j*(tn//rn))*4})'
            loads += [f'let x{j}{suffix}={value};']
        return loads
    chunk=max(size for size in range(1,min(tk,unroll)+1) if tk%size==0) if unroll else tk
    if chunk<tk:
        code += ['mrb=mr*4;']
        if vector_b: code += [f'nrb{j}={column(f"(nr+{j})")}*4;' for j in range(0,rn,2)]
        else: code += ['nrb=nr*4;']
        code += [f'let inner_steps={tk//chunk};while inner_steps {{']
    if pipeline: code += operands(0,'')
    for kk in range(chunk):
        suffix='_next' if pipeline and kk%2 else ''
        if pipeline:
            if kk+1<chunk: code += operands(kk+1,'' if kk%2 else '_next')
        else: code += operands(kk,'')
        for i in range(rm):
            w=f'w{i-1}{suffix}>>32' if vector and rm%2==0 and i%2 else f'w{i}{suffix}'
            for j in range(rn):
                x=f'x{j-1}{suffix}>>32' if vector_b and j%2 else f'x{j}{suffix}'
                code += [f'c{i}{j}=gpu_f32_fma({w},{x},c{i}{j});']
    if chunk<tk:
        code += [f'mrb=gpu_u32_add(mrb,{chunk*pitch_a*4});']
        if vector_b: code += [f'nrb{j}=gpu_u32_add(nrb{j},{chunk*tn*4});' for j in range(0,rn,2)]
        else: code += [f'nrb=gpu_u32_add(nrb,{chunk*tn*4});']
        code += ['inner_steps=gpu_u32_sub(inner_steps,1);}','']
    code += [f'gpu_shared_barrier();base=base+{tk};']
    if streamed: code += [f'a_base=a_base+{tk*4};b_base=b_base+{tk*n*4};']
    if cached: code += [f'a_base=a_base+{tk*4};b_base=b_base+{tk//9*ih*iw*4};']
    code += ['}']
    for i in range(rm):
        code += [f'let row=bm+mr+{i};']
        if m%tm: code += [f'if row<{m} {{']
        if op==12 and has_bias:
            code += [f'let bias_value=gpu_load_u32(bias+({remainder("batch",groups)}*{m}+row)*4);']
            code += [f'c{i}{j}=vk_add(c{i}{j},bias_value);' for j in range(rn)]
        if silu and batch_epilogue:
            # Expose independent SFU requests before consuming any result.
            # Preserve the scalar sigmoid operation order for each output.
            code += [f'let e{j}=vk_sigmoid_exp(c{i}{j});' for j in range(rn)]
            code += [f'let r{j}=gpu_f32_rcp_approx(vk_add(0x3f800000,e{j}));' for j in range(rn)]
            code += [f'c{i}{j}=vk_mul(c{i}{j},vk_sigmoid_finish(c{i}{j},e{j},r{j}));' for j in range(rn)]
        for j in range(rn):
            code += [f'let col=bn+nr+{j if vector_b else j*(tn//rn)};']
            if n%tn: code += [f'if col<{n} {{']
            value=f'c{i}{j}'
            if silu and not batch_epilogue: value=activation(value)
            code += [f'gpu_store_u32(output+((batch*{m}+row)*{n}+col)*4,{value});']
            if n%tn: code += ['}']
        if m%tm: code += ['}']
    shared=(size_a+tk*tn+scratch)*4
    if shared>49152: raise ValueError('tile exceeds shared-memory limit')
    return '\n'.join(code), batches*mb*nb*threads,threads,shared


def element(node, silu=False):
    op,shape,a,b,p = node['op'],node['shape'],node['a'],node['b'],node['params']
    code = ['let other=gpu_launch_word(0);let weights=gpu_launch_word(1);let bias=gpu_launch_word(2);']
    if op in (3,4,5,6,7):
        code += [f'let x=gpu_load_u32(input+({broadcast("index",shape,a)})*4);let y=gpu_load_u32(other+({broadcast("index",shape,b)})*4);']
        value = f'vk_{ {3:"add",4:"sub",5:"mul",6:"div",7:"max"}[op]}(x,y)'
    elif op == 24:
        value = 'vk_sigmoid(gpu_load_u32(input+index*4))'
    elif op == 10:
        strides = [math.prod(a[i+1:]) for i in range(4)]
        terms = []
        for i in range(4):
            coordinate = remainder(quotient('index',math.prod(shape[i+1:])),shape[i])
            terms.append(f'{coordinate}*{strides[p[i]]}')
        value = f'gpu_load_u32(input+({"+".join(terms)})*4)'
    elif op in (25,26):
        axis,start = p[:2]; inner = math.prod(shape[axis+1:]); dim = shape[axis]
        coordinate = remainder(quotient('index',inner),dim)
        outer,tail = quotient('index',inner*dim),remainder('index',inner)
        if op == 26:
            value = f'gpu_load_u32(input+(({outer}*{a[axis]}+{coordinate}+{start})*{inner}+{tail})*4)'
        else:
            code += [f'let coordinate={coordinate};let source=input;let dimension={a[axis]};if coordinate>={a[axis]} {{coordinate=coordinate-{a[axis]};source=other;dimension={b[axis]};}}']
            value = f'gpu_load_u32(source+(({outer}*dimension+coordinate)*{inner}+{tail})*4)'
    elif op == 27:
        scale=p[0]
        src = f'(({quotient("index",shape[2]*shape[3])}*{a[2]}+{quotient(remainder(quotient("index",shape[3]),shape[2]),scale)})*{a[3]}+{quotient(remainder("index",shape[3]),scale)})'
        value = f'gpu_load_u32(input+{src}*4)'
    elif op in (12,14):
        batch,cin,ih,iw=a; _,cout,oh,ow=shape; k,stride,pad,groups=p
        code += [f'let ox={remainder("index",ow)};let oy={remainder(quotient("index",ow),oh)};let channel={remainder(quotient("index",ow*oh),cout)};let batch={quotient("index",ow*oh*cout)};']
        initial='0xff800000' if op==14 else '0'
        code += [f'let sum={initial};']
        channels = 1 if op==14 else cin//groups
        first = 'channel' if op==14 else f'{quotient("channel",cout//groups)}*{channels}'
        code += [f'let first={first};let ci=0;while ci<{channels} {{']
        for ky in range(k):
            code += [f'let iy=oy*{stride}+{ky-pad};if iy>=0 && iy<{ih} {{']
            for kx in range(k):
                code += [f'let ix=ox*{stride}+{kx-pad};if ix>=0 && ix<{iw} {{let x=gpu_load_u32(input+(((batch*{cin}+first+ci)*{ih}+iy)*{iw}+ix)*4);']
                if op==14:
                    code += ['sum=vk_max(sum,x);']
                else:
                    code += [f'sum=gpu_f32_fma(x,gpu_load_u32(weights+((channel*{channels}+ci)*{k*k}+{ky*k+kx})*4),sum);']
                code += ['}']
            code += ['}']
        code += ['ci=ci+1;}']
        if node['bias']:
            code += ['sum=vk_add(sum,gpu_load_u32(bias+channel*4));']
        value = activation('sum') if silu else 'sum'
    elif op==28:
        axis=p[0]; inner=math.prod(shape[axis+1:]); length=shape[axis]
        code += [f'let row=index>>5;let lane=gpu_lane();let start={quotient("row",inner)}*{length*inner}+{remainder("row",inner)};',
                 f'let maximum=0xff800000;let i=lane;while i<{length} {{maximum=vk_max(maximum,gpu_load_u32(input+(start+i*{inner})*4));i=i+32;}}']
        for distance in (16,8,4,2,1):
            code += [f'maximum=vk_max(maximum,gpu_shuffle(maximum,lane^{distance},4294967295));']
        code += [f'let sum=0;i=lane;while i<{length} {{sum=vk_add(sum,vk_exp(vk_sub(gpu_load_u32(input+(start+i*{inner})*4),maximum)));i=i+32;}}',
                 'let reciprocal=gpu_f32_rcp_approx(gpu_warp_sum_f32(sum));',
                 f'i=lane;while i<{length} {{let value=vk_mul(vk_exp(vk_sub(gpu_load_u32(input+(start+i*{inner})*4),maximum)),reciprocal);gpu_store_u32(output+(start+i*{inner})*4,value);i=i+32;}}']
        return '\n'.join(code),math.prod(shape)//length*32,128,0
    else:
        raise ValueError(op)
    code += [f'gpu_store_u32(output+index*4,{value});']
    return '\n'.join(code),math.prod(shape),128,0


def stencil(node, silu=False):
    fallback,work,threads,shared=element(node,silu)
    batch,cin,ih,iw=node['a'];_,cout,oh,ow=node['shape']
    k,stride,pad,groups=node['params']
    first=quotient('channel',cout//groups)
    code=['let weights=gpu_launch_word(1);let bias=gpu_launch_word(2);',
          f'let ox={remainder("index",ow)};let oy={remainder(quotient("index",ow),oh)};let channel={remainder(quotient("index",ow*oh),cout)};let batch={quotient("index",ow*oh*cout)};',
          f'let iy=oy*{stride}-{pad};let ix=ox*{stride}-{pad};',
          f'if iy>=0 && iy<{ih-k+1} && ix>=0 && ix<{iw-k+1} {{',
          f'let source=input+(((batch*{cin}+{first})*{ih}+iy)*{iw}+ix)*4;let lookup=weights+channel*{k*k*4};']
    # The interior needs no padding guards. Issue independent requests before
    # consuming them; boundary pixels retain the scalar operation sequence.
    code += [f'let weight{j}=gpu_load_u32(lookup+{j*4});' for j in range(k*k)]
    code += [f'let pixel{ky*k+kx}=gpu_load_u32(source+{(ky*iw+kx)*4});' for ky in range(k) for kx in range(k)]
    code += ['let sum=0;']
    code += [f'sum=gpu_f32_fma(pixel{j},weight{j},sum);' for j in range(k*k)]
    if node['bias']:code += ['sum=vk_add(sum,gpu_load_u32(bias+channel*4));']
    value=activation('sum') if silu else 'sum'
    code += [f'gpu_store_u32(output+index*4,{value});',f'}}else{{{fallback}}}']
    return '\n'.join(code),work,threads,shared


def input_matrix(node):
    k,stride,pad,groups=node['params']
    batch,cin,ih,iw=node['a'];_,cout,oh,ow=node['shape']
    n,reduction=oh*ow,cin//groups*k*k
    body=f'''let col={remainder("index",n)};let kk={remainder(quotient("index",n),reduction)};let batch={quotient("index",n*reduction)};
let iy={quotient("col",ow)}*{stride}+{remainder(quotient("kk",k),k)}-{pad};let ix={remainder("col",ow)}*{stride}+{remainder("kk",k)}-{pad};
let valid=(iy>=0)*(iy<{ih})*(ix>=0)*(ix<{iw});
let at=((({quotient("batch",groups)}*{cin}+{remainder("batch",groups)}*{cin//groups}+{quotient("kk",k*k)})*{ih}+iy)*{iw}+ix)*valid;
let value=gpu_load_u32(input+at*4)&(0-valid);gpu_store_u32(output+index*4,value);'''
    return body,batch*groups*reduction*n


def residual_epilogue(body, first):
    def store(match):
        text=match[0][:-1]
        call=ast.parse(text,mode='eval').body
        address,value=(ast.get_source_segment(text,arg) for arg in call.args)
        if not any(isinstance(n,ast.Name) and n.id=='output' for n in ast.walk(call.args[0])): raise ValueError('unexpected epilogue output address')
        other='gpu_load_u32('+re.sub(r'\boutput\b','residual',address)+')'
        operands=f'{other},{value}' if first else f'{value},{other}'
        return f'gpu_store_u32({address},vk_add({operands}));'
    # Keep the extra pointer out of the reduction loop's live register set.
    at=body.index('gpu_store_u32(')
    for row in re.finditer(r'(?:let )?row=([^;]+);',body):
        if re.search(r'\bmr\b',row[1]): at=row.start();break
    body=body[:at]+'let residual=gpu_launch_word(7);'+body[at:]
    return re.sub(r'gpu_store_u32\([^;]+\);',store,body)


def graph_nodes(inventory):
    rows = list(struct.iter_unpack('<28q',inventory))
    nodes = [dict(op=r[0],shape=r[8:12],a=r[12:16],b=r[16:20],params=r[20:24],left=r[24],right=r[25],bias=r[26],output=r[27]) for r in rows]
    return nodes


def graph_fusions(nodes, residual_fusion):
    users=defaultdict(list)
    for i,node in enumerate(nodes):
        for key in ('left','right'):
            if node[key]>=0: users[node[key]].append(i)
    fused={}; skip=set()
    for i,node in enumerate(nodes):
        if node['op']!=12 or node['output']: continue
        sigmoid=[j for j in users[i] if nodes[j]['op']==24 and not nodes[j]['output']]
        if len(sigmoid)!=1: continue
        s=sigmoid[0]
        if len(users[s])!=1: continue
        j=users[s][0]
        if nodes[j]['op']==5 and set((nodes[j]['left'],nodes[j]['right']))=={i,s} and set(users[i])=={s,j}:
            fused[i]=j; skip.update((s,j))
    activations=set(fused);residuals={}
    if residual_fusion:
        producers={i:i for i,node in enumerate(nodes) if node['op'] in (12,29) and not node['output']}
        producers.update({target:producer for producer,target in fused.items()})
        for i,node in enumerate(nodes):
            if node['op']!=3: continue
            for key,other_key in (('left','right'),('right','left')):
                target=node[key];producer=producers.get(target);other=node[other_key]
                if producer is None or other<0 or other>=producer: continue
                if nodes[target]['output'] or users[target]!=[i]: continue
                if node['shape']!=node['a'] or node['shape']!=node['b']: continue
                if math.prod(node['shape'])!=math.prod(nodes[producer]['shape']): continue
                residuals[producer]=(other,other_key=='left');fused[producer]=i;skip.add(i);break
    return users,fused,activations,residuals,skip


def alias_root(index, aliases):
    offset=0;seen=set()
    while index in aliases:
        if index in seen: raise ValueError('cyclic tensor placement')
        seen.add(index);index,step=aliases[index];offset+=step
    return index,offset


def fold_adjacent_joins(nodes, aliases, skip):
    folded=[];changed=True
    while changed:
        changed=False
        for i,node in enumerate(nodes):
            if i in skip or node['op']!=25 or math.prod(node['shape'][:node['params'][0]])!=1: continue
            if node['left']<0 or node['right']<0: continue
            base,left=alias_root(node['left'],aliases);other,right=alias_root(node['right'],aliases)
            if base!=other or left+math.prod(node['a'])*4!=right: continue
            target,offset=alias_root(i,aliases)
            if (base,left)!=(target,offset):
                # Relocate the complete source into this join's existing
                # destination. Its slice views must follow that placement.
                # A partial source could overwrite neighboring destination data.
                if base==target or left or math.prod(node['shape'])!=math.prod(nodes[base]['shape']): continue
                aliases[base]=(target,offset)
            skip.add(i);folded.append(i);changed=True
    return folded


def place_joins(nodes, aliases, skip, exclusive=False):
    users=defaultdict(list)
    if exclusive:
        for i,node in enumerate(nodes):
            for key in ('left','right'):
                if node[key]>=0: users[node[key]].append(i)
    placed=[]
    for i,node in reversed(list(enumerate(nodes))):
        if i in skip or node['op']!=25 or math.prod(node['shape'][:node['params'][0]])!=1: continue
        parents=(node['left'],node['right'])
        if any(parent<0 for parent in parents): continue
        if exclusive and any(len(users[parent])!=1 or nodes[parent]['output'] for parent in parents): continue
        target,offset=alias_root(i,aliases);pending={};valid=True
        for parent,step,shape in ((parents[0],0,node['a']),(parents[1],math.prod(node['a'])*4,node['b'])):
            desired=(target,offset+step)
            if alias_root(parent,aliases)==desired: continue
            # A tensor has one physical destination. Existing views and prior
            # placements cannot be redirected to satisfy a second join.
            if parent in aliases or parent==target or math.prod(nodes[parent]['shape'])!=math.prod(shape):valid=False;break
            if parent in pending and pending[parent]!=desired:valid=False;break
            pending[parent]=desired
        if valid:
            aliases.update(pending);skip.add(i);placed.append(i)
    return placed


def compile_plan(inventory, output, compiler, backends, math_mode="fp32", convolution="implicit", tile=None, vector=True, staging=4, streaming=True, batch_epilogue=True, pipeline=True, interior_stencil=False, patch_tiles=False, unroll=0, packed_masks=False, residual_fusion=False, join_views=True, shared_placement=True):
    nodes=graph_nodes(inventory)
    users,fused,activations,residuals,skip=graph_fusions(nodes,residual_fusion)
    # Contiguous slices are views. Single-consumer concatenation operands can
    # write directly into disjoint ranges of their final destination.
    aliases={}; views=set()
    for i,node in enumerate(nodes):
        axis,start=node['params'][:2]
        if node['op']==26 and node['left']>=0 and math.prod(node['a'][:axis])==1:
            aliases[i]=(node['left'],start*math.prod(node['a'][axis+1:])*4)
            views.add(i); skip.add(i)
    placed=place_joins(nodes,aliases,skip,not shared_placement)
    joined=fold_adjacent_joins(nodes,aliases,skip) if join_views else []
    def alias_fields(index):
        if index not in aliases: return (0,0)
        target,offset=alias_root(index,aliases)
        assert offset>=0 and offset+math.prod(nodes[index]['shape'])*4<=math.prod(nodes[target]['shape'])*4
        return target+1,offset
    entries=[]; sources={}; report=[]
    header='''fn gpu_launch_word(index) {return 0;}
fn gpu_thread_x() {return 0;}fn gpu_block_x() {return 0;}fn gpu_lane() {return 0;}
fn gpu_shared_load_u32(offset) {return 0;}fn gpu_shared_store_u32(offset,value) {return 0;}
fn gpu_shared_barrier() {return 0;}fn gpu_shuffle(value,lane,mask) {return value;}
fn gpu_shared_load64(offset) {return 0;}
fn gpu_warp_sum_f32(value) {return value;}
fn gpu_f32_fma(a,b,c) {return vk_add(vk_mul(a,b),c);}
'''
    for i,node in enumerate(nodes):
        if i in skip:
            entries.append(struct.pack('<64s8Q',b'',i,128,1,0,1,0,*alias_fields(i))); continue
        use_tile = node['op']==29 or (node['op']==12 and node['a'][1]//node['params'][3]>1)
        reduction = node['a'][-1] if node['op']==29 else node['a'][1]//node['params'][3]*node['params'][0]*node['params'][0] if node['op']==12 else 0
        use_tensorcore = use_tile and math_mode=='fp32-tc' and reduction%8==0
        use_matrix = convolution=='im2col' and node['op']==12 and node['params'][0]>1 and use_tile and not use_tensorcore and math.prod(node['a'][:2])*node['params'][0]**2*math.prod(node['shape'][2:])<=2**24
        body,work,threads,shared = tiled(node,i in activations,use_matrix,tile,vector,staging,streaming,batch_epilogue,pipeline,patch_tiles,unroll,packed_masks) if use_tile else element(node,i in activations)
        if interior_stencil and node['op']==12 and node['a'][1]//node['params'][3]==1 and node['params'][0]==3:
            body,work,threads,shared=stencil(node,i in activations)
        extra=''
        if use_tensorcore:
            body,work,threads,shared=tensorcore.generate(node,quotient,remainder,i in activations)
            extra=tensorcore.DECLARATIONS
        if i in residuals: body=residual_epilogue(body,residuals[i][1])
        prepare=input_matrix(node)[0] if use_matrix else ''
        body=narrow(body)
        divisors=sorted({int(x) for x in re.findall(r'\bq([0-9]+)\(',body)})
        divisions=''.join(f'fn q{d}(a) {{let q=gpu_u32_mul_hi(a,{((1<<32)+d-1)//d});return gpu_u32_sub(q,gpu_i32_gt(gpu_u32_mul(q,{d}),a));}}\n' for d in divisors)
        locals=list(dict.fromkeys(re.findall(r'let ([a-zA-Z_][a-zA-Z_0-9]*)=',body)))
        body=''.join('let '+name+'=0;' for name in locals)+'\n'+re.sub(r'let ([a-zA-Z_][a-zA-Z_0-9]*)=',r'\1=',body)
        source=f'import "{ROOT}/flex/ml/kernels/ops.flex";\n'+header+DECLARATIONS+divisions+extra+f'fn kernel(index,input,output,count) {{\n{body}\nreturn 0;}}\nfn main() {{return 78;}}\n'
        prep_source=''
        if use_matrix:
            prep=narrow(prepare)
            prep_divisors=sorted({int(x) for x in re.findall(r'\bq([0-9]+)\(',prep)})
            prep_helpers=''.join(f'fn q{d}(a) {{let q=gpu_u32_mul_hi(a,{((1<<32)+d-1)//d});return gpu_u32_sub(q,gpu_i32_gt(gpu_u32_mul(q,{d}),a));}}\n' for d in prep_divisors)
            prep_source=f'import "{ROOT}/flex/ml/kernels/ops.flex";\n'+DECLARATIONS+prep_helpers+f'fn kernel(index,input,output,count) {{{prep}return 0;}}\nfn main() {{return 78;}}\n'
        # Equal matrix kernels can need different image-to-matrix transforms.
        identity=source+'\0'+prep_source if prep_source else source
        name='k'+hashlib.sha256(identity.encode()).hexdigest()[:24]
        sources[name]=source
        if prep_source: sources[name+'-input']=prep_source
        flags=(1 | (2 if node['op']==12 and node['params'][0]==3 else 0)) if use_tensorcore else 4 if use_matrix else 0
        if i in residuals: flags|=8|((residuals[i][0]+1)<<32)
        entries.append(struct.pack('<64s8Q',name.encode(),fused.get(i,i),threads,work,shared,0,flags,*alias_fields(i)))
        report.append(dict(index=i,op=node['op'],shape=node['shape'],kernel=name,silu=i in activations,tiled=use_tile,threads=threads,work=work,shared=shared))
    output.mkdir(parents=True,exist_ok=True)
    for name,source in sources.items():
        path=output/(name+'.flex'); path.write_text(source)
        for backend in backends:
            target,suffix=TARGETS[backend]
            dest=output/(name+'.'+suffix)
            subprocess.run([compiler,'--target',target,str(path),'-o',str(dest)],check=True)
    if math_mode=='fp32-tc':
        for backend in backends:
            if backend=='hip': continue
            target,suffix=TARGETS[backend]
            subprocess.run([compiler,'--target',target,str(ROOT/'flex/ml/kernels/pack.flex'),'-o',str(output/('pack.'+suffix))],check=True)
    digest=hashlib.sha256(inventory).hexdigest()
    for backend in TARGETS:
        for suffix in ('.bin','.json'):
            (output/f'plan-{backend}-{digest}{suffix}').unlink(missing_ok=True)
    (output/f'plan-{digest}.bin').write_bytes(struct.pack('<8sQ64s',b'PPLN0001',len(nodes),digest.encode())+b''.join(entries))
    (output/'plan.json').write_text(json.dumps(dict(fingerprint=digest,mathMode=math_mode,tile=tile,patchTiles=patch_tiles,unroll=unroll,unrollPolicy='largest-divisor',packedMasks=packed_masks,staging=staging,vector=vector,pipeline=pipeline,nodes=len(nodes),fused=len(activations),residuals=len(residuals),views=len(views),joinedViews=len(joined),destinationJoins=len(placed),placements=len(aliases),kernels=len(sources),launches=len(report),schedule=report),indent=2)+'\n')
    print(f'Pup schedule: {len(nodes)} nodes -> {len(report)} launches, {len(activations)} SiLU fusions, {len(sources)} kernel variants',flush=True)


def parse_tile(text):
    try:
        tm,tn,tk,rm,rn=map(int,text.split(','))
    except ValueError:
        raise argparse.ArgumentTypeError('expected TM,TN,TK,RM,RN')
    if any(v<=0 or v&(v-1) for v in (tm,tn,rm,rn)) or tk<=0 or (tk&(tk-1) and tk%9) or tm%rm or tn%rn:
        raise argparse.ArgumentTypeError('block/register tiles must be powers of two; reduction tiles must be powers of two or multiples of nine')
    threads=tm//rm*(tn//rn)
    if threads<32 or threads>1024 or (shared_pitch(tm,tk)+tn)*tk*4>49152:
        raise argparse.ArgumentTypeError('tile exceeds thread or shared-memory limits')
    return tm,tn,tk,rm,rn


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'build/flex/pup-kernels')
    parser.add_argument('--compiler',required=True)
    parser.add_argument('--backend',choices=(*TARGETS,'all'),default='all')
    parser.add_argument('--convolution',choices=['implicit','im2col'],default='implicit')
    parser.add_argument('--tile',type=parse_tile,help='FP32 block and register tile: TM,TN,TK,RM,RN')
    parser.add_argument('--packed-masks',action=argparse.BooleanOptionalAction,default=False,help='carry an invariant padding mask in the high half of each input address token')
    parser.add_argument('--residual-fusion',action=argparse.BooleanOptionalAction,default=False,help='fuse eligible residual additions into convolution and matrix epilogues')
    parser.add_argument('--join-views',action=argparse.BooleanOptionalAction,default=True,help='replace adjacent source-slice concatenations with views and source placement')
    parser.add_argument('--shared-placement',action=argparse.BooleanOptionalAction,default=True,help='place immutable tensors directly into join destinations even when other consumers or outputs share them')
    parser.add_argument('--unroll',type=int,default=0,help='maximum unrolled reduction group; zero unrolls the entire tile')
    parser.add_argument('--patch-tiles',action=argparse.BooleanOptionalAction,default=False,help='align 3x3 convolution reduction tiles with complete image patches')
    parser.add_argument('--interior-stencil',action=argparse.BooleanOptionalAction,default=False,help='batch depthwise convolution loads for pixels without padding')
    parser.add_argument('--pipeline',action=argparse.BooleanOptionalAction,default=True,help='prefetch the next shared-memory operands before computing the current reduction step')
    parser.add_argument('--batch-epilogue',action=argparse.BooleanOptionalAction,default=True,help='overlap independent output activation requests')
    parser.add_argument('--no-streaming',action='store_true',help='recompute tile addresses instead of advancing base pointers')
    parser.add_argument('--staging',type=int,choices=[0,1,2,4,8],default=4,help='batch independent tile loads before storing them')
    parser.add_argument('--vector',action=argparse.BooleanOptionalAction,default=True,help='use aligned pairs for shared-memory tile loads')
    parser.add_argument('--math',choices=['fp32','fp32-tc'],default='fp32')
    args=parser.parse_args()
    if args.unroll<0: parser.error('unroll must be nonnegative')
    backends=list(TARGETS) if args.backend=='all' else [args.backend]
    compile_plan(args.inventory.read_bytes(),args.output,args.compiler,backends,args.math,args.convolution,args.tile,args.vector,args.staging,not args.no_streaming,args.batch_epilogue,args.pipeline,args.interior_stencil,args.patch_tiles,args.unroll,args.packed_masks,args.residual_fusion,args.join_views,args.shared_placement)


if __name__=='__main__':
    main()
