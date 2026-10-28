// Shared static Pup graph execution. Model factories and checkpoints are
// independent of CPU, CUDA/PTX, direct SASS and HIP machine backends.
import "../host/linux.flex";
import "../../build/flex/pup-device.flex";
import "kernels/ops.flex";
import "plan.flex";
global vp_nodes=0;
// Set once before allocating vectors; inference keeps the smaller default.
global vp_graph_limit=8192;
global vp_input=0;
global vp_output=0;
global vp_checkpoint=0;
global vp_bytes=0;
global vp_device=0;
global vp_modules=0;
global vp_kernel_root=0;
global vp_stream=0;
global vp_graph=0;
global vp_inputs=0;
global vp_outputs=0;
global vp_backend=0;
global vp_sha=0;
// Training graphs may select their own convolution and elementwise kernel files.
global vp_convolution_kernel=0;
global vp_binary_kernel=0;
// Output channels per work item of the selected convolution kernel.
global vp_convolution_block=1;
fn vp_require(ok,message) {if !ok {pl_print(2,"Pup runtime: ");pl_print(2,message);pl_print(2,"\n");syscall(231,1,0,0,0,0,0);}return 0;}
fn vp_copy(text) {let n=pl_size(text);let out=alloc(n+1);pb_copy(out,text,n+1);return out;}
fn h_vec() {return alloc(8+vp_graph_limit*8);}
fn h_add(v,x) {let n=load64(v);vp_require(n<vp_graph_limit,"graph list limit");store64(v+8+n*8,x);store64(v,n+1);return x;}
fn h_args(a,b,c,d,e,f) {let v=h_vec();h_add(v,a);h_add(v,b);return v;}
fn vp_at(v,i) {return load64(v+8+i*8);}
fn vp_path(root,leaf) {if load8(leaf)==47 {return vp_copy(leaf);}let out=alloc(4096);let b=alloc(32);pl_builder(b,out,4096);pl_text(b,root);pl_text(b,"/");pl_text(b,leaf);vp_require(!load64(b+24),"path exceeds limit");return out;}
fn vp_suffix(text,suffix) {let n=pl_size(text);let m=pl_size(suffix);let out=alloc(n+m+1);pb_copy(out,text,n);pb_copy(out+n,suffix,m+1);return out;}
fn vp_map(path) {let fd=syscall(2,path,0x80000,0,0,0,0);vp_require(fd>=0,"cannot open checkpoint");let stat=alloc(144);vp_require(!syscall(5,fd,stat,0,0,0,0),"cannot stat checkpoint");vp_bytes=load64(stat+48);vp_require(vp_bytes>=32 && vp_bytes<=134217728,"checkpoint size outside 32 B..128 MiB");let p=syscall(9,0,vp_bytes,1,2,fd,0);syscall(3,fd,0,0,0,0,0);vp_require(p>0,"cannot map checkpoint");return p;}
fn vp_digest(data,size) {if !vp_sha {let library=ffi_open("libcrypto.so.3");vp_require(library,"libcrypto.so.3 unavailable");vp_sha=ffi_symbol(library,"SHA256");vp_require(vp_sha,"SHA256 unavailable");}let digest=alloc(32);ffi_call(vp_sha,data,size,digest,0,0,0);let text=alloc(65);let hex="0123456789abcdef";let i=0;while i<32 {let v=load8(digest+i);store8(text+i*2,load8(hex+(v>>4)));store8(text+i*2+1,load8(hex+(v&15)));i=i+1;}return text;}
fn vp_checkpoint_open(path,sha) {
    vp_checkpoint=vp_map(path);vp_require(pl_equal(vp_digest(vp_checkpoint,vp_bytes),sha),"checkpoint SHA256 mismatch");
    vp_require(load64(vp_checkpoint)==0x3130303056505550 && load64(vp_checkpoint+8)<=4096 && load64(vp_checkpoint+16)==32+256*load64(vp_checkpoint+8) && load64(vp_checkpoint+16)<=vp_bytes && load64(vp_checkpoint+24)==vp_bytes-load64(vp_checkpoint+16),"invalid Pup checkpoint directory");
    let i=0;while i<load64(vp_checkpoint+8) {vp_require(!load8(vp_checkpoint+32+i*256+191),"unterminated tensor name");i=i+1;}return 0;
}
// Backend IDs retain CPU=0 and HIP=1; CUDA/PTX=2, direct SM75 SASS=3.
fn vp_backend_parse(name) {if pl_equal(name,"auto") {return -1;}if pl_equal(name,"cpu") {return 0;}if pl_equal(name,"hip") {return 1;}if pl_equal(name,"cuda") {return 2;}if pl_equal(name,"sass") {return 3;}return -2;}
fn vp_backend_name() {if vp_backend==1 {return "hip";}if vp_backend==2 {return "cuda";}if vp_backend==3 {return "sass";}return "cpu";}
fn vp_kernel_name(op) {if op>=3 && op<=7 {if vp_binary_kernel {return vp_binary_kernel;}return "binary";}if op==24 {return "activation";}if op==10 {return "permute";}if op==25 || op==26 {return "join";}if op==27 {return "resize";}if op==28 {return "softmax";}if op==29 {return "matmul";}if op==12 || op==14 {if vp_convolution_kernel {return vp_convolution_kernel;}return "convolution";}if op==31 {return "recurrence";}if op==30 {return "recurrence-registers";}vp_require(0,"unsupported Pup operation");return 0;}
fn vp_kernel(op) {
    if op>=3 && op<=7 {op=3;}if op==26 {op=25;}if op==14 {op=12;}let slot=vp_modules+op*8;if load64(slot) {return load64(slot);}let suffix=".ptx";if vp_backend==1 {suffix=".hip";}if vp_backend==3 {suffix=".cubin";}
    let path=vp_path(vp_kernel_root,vp_suffix(vp_kernel_name(op),suffix));let size=vp_bytes;let image=vp_map(path);let bytes=vp_bytes;
    let module=device_module(image);vp_require(module,device_error());syscall(11,image,bytes,0,0,0,0);vp_bytes=size;store64(slot,module);return module;
}
fn vp_init(kernel,backend,ordinal) {
    let automatic=backend<0;vp_require(backend>= -1 && backend<=3 && ordinal>=0,"invalid device selection");vp_plan_before=0;vp_plan_range=0;vp_active_plan=0;vp_math_mode="fp32";vp_nodes=h_vec();vp_modules=alloc(256);vp_kernel_root=kernel;
    if backend<0 {backend=0;if cuda_device_count()>ordinal {backend=2;}else if hip_device_count()>ordinal {backend=1;}}
    vp_backend=backend;if !backend {return 0;}device_select_hip(backend==1);
    vp_device=device_context_device(ordinal);vp_require(vp_device,device_error());vp_stream=device_stream();vp_require(vp_stream,device_error());
    if backend==2 || backend==3 {
        let device=device_device(ordinal);let major=device_device_attribute(device,75);let minor=device_device_attribute(device,76);
        if backend==3 {vp_require(major==7 && minor==5,"direct SASS requires SM75; select cuda for PTX");}
        // Auto prefers native SASS on the exact supported architecture.
        if automatic && major==7 && minor==5 {vp_backend=3;}
    }
    return 0;
}
fn vp_check(status) {if status {vp_require(0,device_error());}return status;}
fn vp_buffer(size) {if !vp_backend {return alloc(size);}let out=device_buffer(size);vp_require(out,device_error());return out;}
fn vp_upload(out,data,size) {if !vp_backend {pb_copy(out,data,size);return 0;}return vp_check(device_upload(out,data,size));}
fn pup_shape(rank,a,b,c,d) {let s=alloc(40);store64(s,rank);store64(s+8,a);store64(s+16,b);store64(s+24,c);store64(s+32,d);return s;}
fn vp_count(shape) {let i=0;let count=1;vp_require(load64(shape)<=4,"tensor rank exceeds four");while i<load64(shape) {let d=load64(shape+8+i*8);vp_require(d>0 && count<=16777216/d,"invalid tensor shape");count=count*d;i=i+1;}return count;}
// Tensor descriptor: data,count,shape,op,a,b,weights,bias,params[4],
// device-meta,argument pointers,launch configuration,function.
fn vp_tensor(shape,op,a,b) {let t=alloc(128);store64(t+8,vp_count(shape));store64(t+16,shape);store64(t+24,op);store64(t+32,a);store64(t+40,b);store64(t,vp_buffer(load64(t+8)*4));if op {h_add(vp_nodes,t);}return t;}
fn vp_dim(t,axis) {return load64(load64(t+16)+8+axis*8);}
fn vp_rank(t) {return load64(load64(t+16));}
fn vp_shape_copy(t) {let s=alloc(40);pb_copy(s,load64(t+16),40);return s;}
fn vp_parameter(name,shape) {
    if vp_compile_only {return vp_tensor(shape,0,0,0);}
    let n=load64(vp_checkpoint+8);let i=0;let found=0;
    while i<n {let record=vp_checkpoint+32+i*256;if pl_equal(record,name) {vp_require(!found,"duplicate checkpoint tensor");found=record;}i=i+1;}
    vp_require(found,"checkpoint tensor is missing");vp_require(load64(found+192)==load64(shape) && load64(found+200)==vp_count(shape),"checkpoint tensor shape differs from Pup");i=0;while i<load64(shape) {vp_require(load64(found+216+i*8)==load64(shape+8+i*8),"checkpoint tensor dimension differs from Pup");i=i+1;}
    let bytes=load64(found+200)*4;let offset=load64(found+208);let base=load64(vp_checkpoint+16);vp_require(offset>=0 && offset<=vp_bytes-base && bytes<=vp_bytes-base-offset,"checkpoint tensor payload exceeds file");let t=vp_tensor(shape,0,0,0);vp_upload(load64(t),vp_checkpoint+base+offset,bytes);return t;
}
fn pup_tensor(name,shape) {if pup_model_input(name) {return vp_tensor(shape,0,0,0);}return vp_parameter(name,shape);}
fn pup_scalar(bits) {let t=vp_tensor(pup_shape(0,1,1,1,1),0,0,0);let p=alloc(4);pb_put32(p,bits);vp_upload(load64(t),p,4);return t;}
fn pup_binary(op,a,b) {let rank=pb_max(vp_rank(a),vp_rank(b));let s=pup_shape(rank,1,1,1,1);let i=0;while i<rank {let x=1;let y=1;let ai=i-rank+vp_rank(a);let bi=i-rank+vp_rank(b);if ai>=0 {x=vp_dim(a,ai);}if bi>=0 {y=vp_dim(b,bi);}vp_require(x==y || x==1 || y==1,"broadcast dimensions differ");store64(s+8+i*8,pb_max(x,y));i=i+1;}return vp_tensor(s,op,a,b);}
fn pup_reshape(a,shape) {vp_require(vp_count(shape)==load64(a+8),"reshape changes element count");let t=alloc(128);pb_copy(t,a,128);store64(t+16,shape);store64(t+24,0);return t;}
fn pup_permute(a,axes) {let s=vp_shape_copy(a);let i=0;while i<vp_rank(a) {store64(s+8+i*8,vp_dim(a,load64(axes+8+i*8)));i=i+1;}let t=vp_tensor(s,10,a,0);i=0;while i<4 {let axis=i;if i>=4-vp_rank(a) {axis=4-vp_rank(a)+load64(axes+8+(i-4+vp_rank(a))*8);}store64(t+64+i*8,axis);i=i+1;}return t;}
fn pup_conv2d(a,name,channels,k,stride,pad,bias,groups,transpose) {vp_require(!transpose,"transpose convolution unsupported in this inference adapter");let cin=vp_dim(a,1);let s=pup_shape(4,vp_dim(a,0),channels,(vp_dim(a,2)+2*pad-k)/stride+1,(vp_dim(a,3)+2*pad-k)/stride+1);let t=vp_tensor(s,12,a,0);let w=vp_parameter(vp_suffix(name,".weight"),pup_shape(4,channels,cin/groups,k,k));store64(t+48,load64(w));if bias {let v=vp_parameter(vp_suffix(name,".bias"),pup_shape(1,channels,1,1,1));store64(t+56,load64(v));}store64(t+64,k);store64(t+72,stride);store64(t+80,pad);store64(t+88,groups);return t;}
fn pup_maxpool2d(a,k,stride,pad) {let s=vp_shape_copy(a);store64(s+24,(vp_dim(a,2)+2*pad-k)/stride+1);store64(s+32,(vp_dim(a,3)+2*pad-k)/stride+1);let t=vp_tensor(s,14,a,0);store64(t+64,k);store64(t+72,stride);store64(t+80,pad);store64(t+88,1);return t;}
fn pup_sigmoid(a) {return vp_tensor(vp_shape_copy(a),24,a,0);}
fn pup_concat(a,b,axis) {let s=vp_shape_copy(a);store64(s+8+axis*8,vp_dim(a,axis)+vp_dim(b,axis));let t=vp_tensor(s,25,a,b);store64(t+64,axis+4-vp_rank(a));return t;}
fn pup_slice(a,axis,start,length) {let s=vp_shape_copy(a);store64(s+8+axis*8,length);let t=vp_tensor(s,26,a,0);store64(t+64,axis+4-vp_rank(a));store64(t+72,start);return t;}
fn pup_upsample2d(a,scale) {let s=vp_shape_copy(a);store64(s+24,vp_dim(a,2)*scale);store64(s+32,vp_dim(a,3)*scale);let t=vp_tensor(s,27,a,0);store64(t+64,scale);return t;}
fn pup_softmax(a,axis) {let t=vp_tensor(vp_shape_copy(a),28,a,0);store64(t+64,axis+4-vp_rank(a));return t;}
fn pup_batch_matmul(a,b) {let s=vp_shape_copy(a);store64(s+vp_rank(a)*8,vp_dim(b,vp_rank(b)-1));return vp_tensor(s,29,a,b);}
fn vp_metadata_shape(out,t) {let i=0;while i<4 {let d=1;if t && i>=4-vp_rank(t) {d=vp_dim(t,i-4+vp_rank(t));}store64(out+i*8,d);i=i+1;}return 0;}
// Every GPU launch descriptor is allocated once, then captured as a device graph.
// The shared device API owns each backend's configuration layout.
fn vp_launch_plan() {let i=0;while i<load64(vp_nodes) {let t=vp_at(vp_nodes,i);if load64(t+120) {if vp_plan_before {vp_plan_pack_launch(load64(vp_plan_before+i*16));vp_plan_pack_launch(load64(vp_plan_before+i*16+8));}vp_check(device_dispatch(load64(t+120),load64(t+112),load64(t+104)));}i=i+1;}return 0;}
fn pup_finish(inputs,outputs) {
    vp_require(load64(inputs)>0 && load64(outputs)>0,"Pup graph needs inputs and outputs");vp_inputs=inputs;vp_outputs=outputs;vp_input=vp_at(vp_at(inputs,0),1);vp_output=vp_at(outputs,0);
    vp_host_metadata=alloc(load64(vp_nodes)*192);let i=0;while i<load64(vp_nodes) {
        let t=vp_at(vp_nodes,i);let m=vp_host_metadata+i*192;store64(m,load64(t+24));vp_metadata_shape(m+64,t);vp_metadata_shape(m+96,load64(t+32));vp_metadata_shape(m+128,load64(t+40));pb_copy(m+160,t+64,32);
        if vp_backend {
            let d=device_buffer(192);vp_require(d,device_error());vp_check(device_upload(d,m,192));store64(t+96,d);
            let count=load64(t+8);if load64(t+24)==28 {count=count/load64(m+64+load64(m+160)*8);}if load64(t+24)==12 {count=count/vp_convolution_block;}
            let values=alloc(88);let args=alloc(88);store64(values,load64(load64(t+32)));store64(values+8,load64(t));store64(values+16,count);
            if load64(t+40) {store64(values+24,load64(load64(t+40)));}store64(values+32,load64(t+48));store64(values+40,load64(t+56));store64(values+48,d);
            let word=0;while word<11 {store64(args+word*8,values+word*8);word=word+1;}
            let config=device_config((count+127)/128,1,1,128,1,1,0,vp_stream);
            // A recurrence is one block, synchronized per step; its thread count is a parameter.
            if load64(t+24)==30 || load64(t+24)==31 {config=device_config(1,1,1,load64(t+88),1,1,load64(t+64)*load64(t+72)*16,vp_stream);}vp_require(config,device_error());store64(t+104,args);store64(t+112,config);
            let function=device_function(vp_kernel(load64(t+24)),"flex_kernel");vp_require(function,device_error());store64(t+120,function);
        }else {store64(t+96,m);}i=i+1;
    }
    if vp_backend {
        vp_plan_apply();vp_check(device_capture_begin(vp_stream));vp_launch_plan();let graph=device_capture_end(vp_stream);vp_require(graph,device_error());
        vp_graph=device_graph_instance(graph);vp_require(vp_graph,device_error());vp_check(device_graph_close(graph));vp_check(device_graph_upload(vp_graph,vp_stream));vp_check(device_stream_wait(vp_stream));
    }
    return vp_output;
}
fn vp_execute() {
    if vp_backend {vp_check(device_graph_launch(vp_graph,vp_stream));vp_check(device_stream_wait(vp_stream));if vp_plan_range {vp_plan_range_check();}return 0;}
    let i=0;while i<load64(vp_nodes) {let t=vp_at(vp_nodes,i);let a=load64(load64(t+32));let b=0;if load64(t+40) {b=load64(load64(t+40));}let j=0;
        while j<load64(t+8) {pb_put32(load64(t)+j*4,vk_element(j,a,b,load64(t+48),load64(t+56),load64(t+96)));j=j+1;}i=i+1;}return 0;
}
fn vp_read_tensor(tensor,out) {let n=load64(tensor+8)*4;if vp_backend {return vp_check(device_download(out,load64(tensor),n));}pb_copy(out,load64(tensor),n);return 0;}
fn vp_read_output(out) {return vp_read_tensor(vp_output,out);}
