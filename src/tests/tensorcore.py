"""Optional three-product tensor-core lowering with FP32 accumulation.

FP32 inputs and outputs; FP16 high parts and scaled FP16 residuals approximate
FP32 products. This is a separate numerical mode, never strict FP32 arithmetic.
"""
import math


def generate_scalar(node, quotient, remainder, silu=False):
    op,shape,a,p = node['op'],node['shape'],node['a'],node['params']
    if op==12:
        kernel,stride,pad,groups=p
        batch,cin,ih,iw=a;_,cout,oh,ow=shape
        m,n,reduction=cout//groups,oh*ow,cin//groups*kernel*kernel
        batches=batch*groups
    else:
        m,n,reduction=shape[-2],shape[-1],a[-1]
        batches=math.prod(shape[:-2]);groups=1
    tm,tn,threads=16,32,128
    mb,nb=(m+tm-1)//tm,(n+tn-1)//tn
    code=[f'let tid=gpu_thread_x();let lane=gpu_lane();let block=gpu_block_x();let bm={remainder(quotient("block",nb),mb)}*16;let bn={remainder("block",nb)}*32+(tid>>5)*8;let batch={quotient("block",mb*nb)};',
          'let row=bm+(lane>>2);let col=bn+(lane>>2);let offset=tid*8;let weights=gpu_launch_word(1);let bias=gpu_launch_word(2);let other=gpu_launch_word(0);let total0=0;let total1=0;let base=0;',
          f'while base<{reduction} {{let kk=base+(lane&3)*2;']
    for i in range(4):
        r=f'(row+{8 if i>=2 else 0})';k=f'(kk+{i%2})'
        code += [f'let valid=({r}<{m})*({k}<{reduction});']
        if op==12:
            address=f'(({remainder("batch",groups)}*{m}+{r})*{reduction}+{k})'
            source='weights'
        else:
            address=f'((batch*{m}+{r})*{reduction}+{k})';source='input'
        code += [f'let a{i}=gpu_load_u32({source}+({address}*valid)*4)&(0-valid);']
    for i in range(2):
        k=f'(kk+{i})'
        code += [f'let valid=(col<{n})*({k}<{reduction});']
        if op==12:
            if kernel==1 and stride==1 and pad==0:
                address=f'(({quotient("batch",groups)}*{cin}+{remainder("batch",groups)}*{cin//groups}+{k})*{n}+col)'
            else:
                code += [f'let iy={quotient("col",ow)}*{stride}+{remainder(quotient(k,kernel),kernel)}-{pad};let ix={remainder("col",ow)}*{stride}+{remainder(k,kernel)}-{pad};valid=valid*(iy>=0)*(iy<{ih})*(ix>=0)*(ix<{iw});']
                address=f'((({quotient("batch",groups)}*{cin}+{remainder("batch",groups)}*{cin//groups}+{quotient(k,kernel*kernel)})*{ih}+iy)*{iw}+ix)'
            source='input'
        else:
            address=f'((batch*{reduction}+{k})*{n}+col)';source='other'
        code += [f'let b{i}=gpu_load_u32({source}+({address}*valid)*4)&(0-valid);']
    code += ['let av0=a0|(a1<<32);let av1=a2|(a3<<32);let bv=b0|(b1<<32);',
             'let ah=gpu_f16_pair_hi(av0)|(gpu_f16_pair_hi(av1)<<32);let al=gpu_f16_pair_lo(av0)|(gpu_f16_pair_lo(av1)<<32);let bh=gpu_f16_pair_hi(bv);let bl=gpu_f16_pair_lo(bv);',
             'let cross0=gpu_mma_f16x4(al,bh,0,0,offset);let cross1=gpu_shared_load64(offset);',
             'cross0=gpu_mma_f16x4(ah,bl,cross0,cross1,offset);cross1=gpu_shared_load64(offset);',
             'total0=gpu_f32x2_fma(cross0,0x3a8000003a800000,total0);',
             'total1=gpu_f32x2_fma(cross1,0x3a8000003a800000,total1);',
             'total0=gpu_mma_f16x4(ah,bh,total0,total1,offset);total1=gpu_shared_load64(offset);base=base+8;}']
    for i in range(4):
        row=f'(bm+(lane>>2)+{8 if i>=2 else 0})'
        col=f'(bn+(lane&3)*2+{i%2})'
        value=f'total{i//2}'+('>>32' if i%2 else '&0xffffffff')
        code += [f'if {row}<{m} && {col}<{n} {{let value={value};']
        if node['bias']:
            code += [f'value=vk_add(value,gpu_load_u32(bias+({remainder("batch",groups)}*{m}+{row})*4));']
        if silu: code += ['value=vk_mul(value,vk_sigmoid(value));']
        code += [f'gpu_store_u32(output+((batch*{m}+{row})*{n}+{col})*4,value);}}']
    return '\n'.join(code),batches*mb*nb*threads,threads,threads*8


DECLARATIONS='''
fn gpu_f16_pair_hi(value) {return (value&65535)|((value>>16)&0xffff0000);}
fn gpu_f16_pair_lo(value) {return ((value>>16)&65535)|((value>>32)&0xffff0000);}
fn gpu_mma_f16x4(a,b,c,d,offset) {return 0;}
fn gpu_f32x2_fma(a,b,c) {return 0;}
'''




def generate(node, quotient, remainder, silu=False):
    op,shape,a,p=node['op'],node['shape'],node['a'],node['params']
    if op==12:
        kernel,stride,pad,groups=p
        batch,cin,ih,iw=a;_,cout,oh,ow=shape
        m,n,reduction=cout//groups,oh*ow,cin//groups*kernel*kernel
        batches=batch*groups
    else:
        m,n,reduction=shape[-2],shape[-1],a[-1]
        batches=math.prod(shape[:-2]);groups=1
    if reduction%8 or (op==12 and kernel not in (1,3)) or (op==12 and kernel==3 and (cin//groups)%8):
        return generate_scalar(node,quotient,remainder,silu)
    if op==12 and kernel==1 and (stride!=1 or pad!=0):
        return generate_scalar(node,quotient,remainder,silu)
    phases=9 if op==12 and kernel==3 else 1
    mb=(m+15)//16
    parts=2 if n>=64 and batches*mb*((n+63)//64)>=72 else 1
    nb=(n+32*parts-1)//(32*parts)
    code=[f'let tid=gpu_thread_x();let lane=gpu_lane();let block=gpu_block_x();let bm={remainder(quotient("block",nb),mb)}*16;let bn={remainder("block",nb)}*{32*parts}+(tid>>5)*{8*parts};let batch={quotient("block",mb*nb)};',
          'let row=bm+(lane>>2);let col=bn+(lane>>2);let lane_k=(lane&3)*2;let offset=tid*8;',
          'let weights=gpu_launch_word(1);let bias=gpu_launch_word(2);let other=gpu_launch_word(0);let base=0;',
          f'let wr0=(row*{reduction}+lane_k)*(row<{m});let wr1=((row+8)*{reduction}+lane_k)*(row+8<{m});']
    code += [f'let total{part}_{i}=0;' for part in range(parts) for i in range(2)]
    if op==12:
        code += [f'wr0=wr0+{remainder("batch",groups)}*{m*reduction};wr1=wr1+{remainder("batch",groups)}*{m*reduction};']
    else:
        code += [f'wr0=wr0+batch*{m*reduction};wr1=wr1+batch*{m*reduction};weights=input;']
    for phase in range(phases):
        for part in range(parts):
            column=f'(col+{part*8})'
            k='lane_k'
            code += [f'let valid={column}<{n};']
            if op==12 and kernel==3:
                code += [f'let iy={quotient(column,ow)}*{stride}+{phase//3}-{pad};let ix={remainder(column,ow)}*{stride}+{phase%3}-{pad};valid=valid*(iy>=0)*(iy<{ih})*(ix>=0)*(ix<{iw});']
                address=f'((({quotient("batch",groups)}*{cin}+{remainder("batch",groups)}*{cin//groups}+{k})*{ih}+iy)*{iw}+ix)'
            elif op==12:
                address=f'(({quotient("batch",groups)}*{cin}+{remainder("batch",groups)}*{cin//groups}+{k})*{n}+{column})'
            else:
                address=f'((batch*{reduction}+{k})*{n}+{column})'
            code += [f'let lookup{phase}_{part}_0=({address}*valid)|(valid<<31);']
    code += [f'while base<{reduction//9 if phases==9 else reduction} {{']
    for phase in range(phases):
        code += [f'let av0=gpu_load_u64(weights+(wr0+base+{phase*(cin//groups) if phases==9 else 0})*4);let av1=gpu_load_u64(weights+(wr1+base+{phase*(cin//groups) if phases==9 else 0})*4);',
                 'let ah=gpu_f16_pair_hi(av0)|(gpu_f16_pair_hi(av1)<<32);let al=gpu_f16_pair_lo(av0)|(gpu_f16_pair_lo(av1)<<32);']
        for part in range(parts):
            code += [f'let entry=lookup{phase}_{part}_0;let valid=entry>>31;let address=(base*{ih*iw if op==12 else n}+(entry&0x7fffffff))*valid;',
                     f'let b0=gpu_load_u32({"input" if op==12 else "other"}+address*4)&(0-valid);let b1=gpu_load_u32({"input" if op==12 else "other"}+(address+{ih*iw if op==12 else n}*valid)*4)&(0-valid);']
            code += ['let bv=b0|(b1<<32);let bh=gpu_f16_pair_hi(bv);let bl=gpu_f16_pair_lo(bv);',
                     'let cross0=gpu_mma_f16x4(al,bh,0,0,offset);let cross1=gpu_shared_load64(offset);cross0=gpu_mma_f16x4(ah,bl,cross0,cross1,offset);cross1=gpu_shared_load64(offset);',
                     f'total{part}_0=gpu_f32x2_fma(cross0,0x3a8000003a800000,total{part}_0);total{part}_1=gpu_f32x2_fma(cross1,0x3a8000003a800000,total{part}_1);',
                     f'total{part}_0=gpu_mma_f16x4(ah,bh,total{part}_0,total{part}_1,offset);total{part}_1=gpu_shared_load64(offset);']
    code += ['base=base+8;}']
    for part in range(parts):
        for i in range(4):
            row=f'(bm+(lane>>2)+{8 if i>=2 else 0})';col=f'(bn+(lane&3)*2+{part*8+i%2})'
            value=f'total{part}_{i//2}'+('>>32' if i%2 else '&0xffffffff')
            code += [f'if {row}<{m} && {col}<{n} {{let value={value};']
            if node['bias']: code += [f'value=vk_add(value,gpu_load_u32(bias+({remainder("batch",groups)}*{m}+{row})*4));']
            if silu: code += ['value=vk_mul(value,vk_sigmoid(value));']
            code += [f'gpu_store_u32(output+((batch*{m}+{row})*{n}+{col})*4,value);}}']
    return '\n'.join(code),batches*mb*nb*128,128,1024
