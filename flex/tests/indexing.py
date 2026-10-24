"""Narrow bounded tensor coordinates while retaining 64-bit device pointers."""
import ast
import operator
import re

POINTERS = {'input','output','other','weights','bias','source','mrb','nrb','lookup','a_base','b_base','residual'}
BINARY = {ast.Add:'gpu_u32_add',ast.Sub:'gpu_u32_sub',ast.Mult:'gpu_u32_mul'}
COMPARE = {ast.Lt:'gpu_i32_lt',ast.LtE:'gpu_i32_le',ast.Gt:'gpu_i32_gt',ast.GtE:'gpu_i32_ge',ast.Eq:'gpu_u32_eq',ast.NotEq:'gpu_u32_ne'}


def expression(text):
    def lower(node):
        if isinstance(node,ast.BinOp):
            left,right=node.left,node.right
            if isinstance(left,ast.Constant) and isinstance(right,ast.Constant):
                operations={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.BitAnd:operator.and_,ast.BitOr:operator.or_,ast.BitXor:operator.xor,ast.LShift:operator.lshift,ast.RShift:operator.rshift}
                return str(operations[type(node.op)](left.value,right.value)),False
            if isinstance(right,ast.Constant):
                if (isinstance(node.op,(ast.Add,ast.Sub,ast.BitOr,ast.BitXor)) and right.value==0) or (isinstance(node.op,ast.Mult) and right.value==1): return lower(left)
                if isinstance(node.op,ast.Mult) and right.value==0: return '0',False
            if isinstance(left,ast.Constant):
                if (isinstance(node.op,(ast.Add,ast.BitOr,ast.BitXor)) and left.value==0) or (isinstance(node.op,ast.Mult) and left.value==1): return lower(right)
                if isinstance(node.op,ast.Mult) and left.value==0: return '0',False
        if isinstance(node,ast.Name): return node.id,node.id in POINTERS or bool(re.fullmatch(r'nrb[0-9]+',node.id))
        if isinstance(node,ast.Constant): return str(node.value),False
        if isinstance(node,ast.Call):
            return node.func.id+'('+','.join(lower(a)[0] for a in node.args)+')',node.func.id=='gpu_address_f32'
        if isinstance(node,ast.BinOp):
            left,lp=lower(node.left);right,rp=lower(node.right)
            kind=type(node.op)
            if kind==ast.Add and lp and isinstance(node.right,ast.BinOp) and isinstance(node.right.op,ast.Mult) and isinstance(node.right.right,ast.Constant) and node.right.right.value==4:
                return f'gpu_address_f32({left},{lower(node.right.left)[0]})',True
            if kind in BINARY and not lp and not rp:
                # Fused index multiply-add maps to one native IMAD/mad.u32.
                if kind==ast.Add and isinstance(node.left,ast.BinOp) and isinstance(node.left.op,ast.Mult):
                    return f'gpu_u32_mad({lower(node.left.left)[0]},{lower(node.left.right)[0]},{right})',False
                return f'{BINARY[kind]}({left},{right})',False
            symbol={ast.Add:'+',ast.Sub:'-',ast.Mult:'*',ast.BitAnd:'&',ast.BitOr:'|',ast.BitXor:'^',ast.LShift:'<<',ast.RShift:'>>'}[kind]
            return f'({left}{symbol}{right})',lp or rp
        if isinstance(node,ast.UnaryOp):
            value,pointer=lower(node.operand)
            if isinstance(node.op,ast.USub): return f'gpu_u32_sub(0,{value})',False
            if isinstance(node.op,ast.Invert): return f'({value}^4294967295)',False
        if isinstance(node,ast.Compare):
            assert len(node.ops)==1
            return f'{COMPARE[type(node.ops[0])]}({lower(node.left)[0]},{lower(node.comparators[0])[0]})',False
        if isinstance(node,ast.BoolOp):
            assert isinstance(node.op,ast.And)
            values=[lower(v)[0] for v in node.values]
            while len(values)>1: values=[f'gpu_u32_mul({values[0]},{values[1]})',*values[2:]]
            return values[0],False
        raise ValueError(ast.dump(node))
    return lower(ast.parse(text.replace('&&',' and '),mode='eval').body)[0]


def narrow(body):
    pieces=re.split(r'([;{}])',body)
    valid_one=False
    for i,piece in enumerate(pieces):
        text=piece.strip()
        if not text or text in (';','{','}','else'): continue
        valid_assignment=re.match(r'^let valid=(.+)$|^valid=(.+)$',text,re.S)
        if valid_assignment: valid_one=(valid_assignment[1] or valid_assignment[2])=='1'
        elif valid_one: text=re.sub(r'\bvalid\b','1',text)
        condition=re.match(r'^(if|while)\s+(.+)$',text,re.S)
        assignment=re.match(r'^((?:let\s+)?[A-Za-z_][A-Za-z_0-9]*=)(.+)$',text,re.S)
        if condition: pieces[i]=condition[1]+' '+expression(condition[2])+' '
        elif assignment: pieces[i]=assignment[1]+expression(assignment[2])
        else: pieces[i]=expression(text)
    return ''.join(pieces)


DECLARATIONS = '''
fn gpu_address_f32(pointer,index) {return pointer+(index&0xffffffff)*4;}
fn gpu_u32_add(a,b) {return (a+b)&0xffffffff;}
fn gpu_u32_sub(a,b) {return (a-b)&0xffffffff;}
fn gpu_u32_mul(a,b) {return (a*b)&0xffffffff;}
fn gpu_u32_mad(a,b,c) {return (a*b+c)&0xffffffff;}
fn gpu_u32_mul_hi(a,b) {return (((a&0xffffffff)*(b&0xffffffff))>>32)&0xffffffff;}
fn gpu_i32_lt(a,b) {return ((a^0x80000000)&0xffffffff)<((b^0x80000000)&0xffffffff);}
fn gpu_i32_le(a,b) {return !gpu_i32_lt(b,a);}
fn gpu_i32_gt(a,b) {return gpu_i32_lt(b,a);}
fn gpu_i32_ge(a,b) {return !gpu_i32_lt(a,b);}
fn gpu_u32_eq(a,b) {return (a&0xffffffff)==(b&0xffffffff);}
fn gpu_u32_ne(a,b) {return (a&0xffffffff)!=(b&0xffffffff);}
'''
