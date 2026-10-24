// A shape/edge fingerprint selects an optional ahead-of-time device schedule.
// Records contain only dimensions, operations and producer indices, never weights.
global vp_compile_only=0;
global vp_math_mode=0;
global vp_plan_range=0;
global vp_plan_range_host=0;
global vp_inventory=0;
global vp_host_metadata=0;
global vp_plan_before=0;
global vp_plan_workspace_a=0;
global vp_plan_workspace_b=0;
global vp_plan_workspace_conv=0;
global vp_active_plan=0;
fn vp_producer(t) {if !t {return -1;}let data=load64(t);let i=0;while i<load64(vp_nodes) {if load64(vp_at(vp_nodes,i))==data {return i;}i=i+1;}return -1;}
fn vp_plan_inventory() {
    let count=load64(vp_nodes);let out=alloc(count*224);let i=0;
    while i<count {let t=vp_at(vp_nodes,i);let row=out+i*224;pb_copy(row,vp_host_metadata+i*192,192);
        store64(row+192,vp_producer(load64(t+32)));store64(row+200,vp_producer(load64(t+40)));store64(row+208,load64(t+56)!=0);
        let j=0;while j<load64(vp_outputs) {if load64(vp_at(vp_outputs,j))==load64(t) {store64(row+216,1);}j=j+1;}i=i+1;
    }vp_inventory=out;return out;
}
fn vp_plan_range_check() {vp_check(device_download(vp_plan_range_host,vp_plan_range,8));vp_require(!load64(vp_plan_range_host),"tensor-core operand outside finite FP16 range; rebuild with fp32 math");return 0;}
fn vp_plan_pack_layout(function,input,output,count,channels,spatial) {
    let values=alloc(88);let args=alloc(88);store64(values,input);store64(values+8,output);store64(values+16,count);store64(values+24,vp_plan_range);store64(values+32,channels);store64(values+40,spatial);let i=0;while i<11 {store64(args+i*8,values+i*8);i=i+1;}
    let record=alloc(24);store64(record,function);store64(record+8,device_config((count+255)/256,1,1,128,1,1,0,vp_stream));store64(record+16,args);return record;
}
fn vp_plan_pack(function,input,output,count) {return vp_plan_pack_layout(function,input,output,count,0,0);}
fn vp_plan_prepare(function,input,output,count) {let record=vp_plan_pack(function,input,output,count);store64(record+8,device_config((count+127)/128,1,1,128,1,1,0,vp_stream));return record;}
fn vp_plan_pack_launch(record) {if record {vp_check(device_dispatch(load64(record),load64(record+8),load64(record+16)));}return 0;}
fn vp_plan_file(digest) {
    let name=vp_suffix(vp_suffix(vp_suffix("plan-",vp_backend_name()),"-"),digest);let path=vp_path(vp_kernel_root,vp_suffix(name,".bin"));let fd=syscall(2,path,0x80000,0,0,0,0);
    if fd>=0 {syscall(3,fd,0,0,0,0,0);return path;}return vp_path(vp_kernel_root,vp_suffix(vp_suffix("plan-",digest),".bin"));
}
fn vp_plan_apply() {
    let count=load64(vp_nodes);let inventory=vp_plan_inventory();let digest=vp_digest(inventory,count*224);
    let path=vp_plan_file(digest);let fd=syscall(2,path,0x80000,0,0,0,0);if fd<0 {return 0;}syscall(3,fd,0,0,0,0,0);vp_active_plan=path;
    let old_size=vp_bytes;let plan=vp_map(path);vp_require(vp_bytes==80+count*128 && load64(plan)==0x313030304e4c5050 && load64(plan+8)==count,"invalid Pup schedule");let stored_digest=alloc(65);pb_copy(stored_digest,plan+16,64);vp_require(pl_equal(stored_digest,digest),"Pup schedule fingerprint differs");
    // Placement targets are flattened by the compiler and never themselves
    // redirected. Update reshape views and the already-built launch arguments.
    let original=alloc(count*8);let alias_index=0;
    while alias_index<count {store64(original+alias_index*8,load64(vp_at(vp_nodes,alias_index)));alias_index=alias_index+1;}
    alias_index=0;while alias_index<count {
        let entry=plan+80+alias_index*128;let target=load64(entry+112);let offset=load64(entry+120);
        if target {vp_require(target>0 && target<=count && offset>=0 && offset%4==0,"invalid tensor placement");let destination=vp_at(vp_nodes,target-1);let tensor=vp_at(vp_nodes,alias_index);vp_require(offset<=load64(destination+8)*4 && load64(tensor+8)*4<=load64(destination+8)*4-offset,"tensor placement exceeds destination");store64(tensor,load64(original+(target-1)*8)+offset);}
        alias_index=alias_index+1;
    }
    alias_index=0;while alias_index<count {
        let tensor=vp_at(vp_nodes,alias_index);let side=0;
        while side<2 {let source=load64(tensor+32+side*8);if source {let before=load64(source);let j=0;while j<count {if before==load64(original+j*8) {store64(source,load64(vp_at(vp_nodes,j)));j=count;}else {j=j+1;}}}side=side+1;}
        let args=load64(tensor+104);store64(load64(args),load64(load64(tensor+32)));store64(load64(args+8),load64(tensor));if load64(tensor+40) {store64(load64(args+24),load64(load64(tensor+40)));}
        alias_index=alias_index+1;
    }
    let names=h_vec();let functions=h_vec();let i=0;let pack=0;let workspace_a=0;let workspace_b=0;let workspace_conv=0;
    while i<count {let entry=plan+80+i*128;if load64(entry+104)&4 {let m=vp_host_metadata+i*192;let elements=load64(m+64)*load64(m+104)*load64(m+160)*load64(m+160)*load64(m+80)*load64(m+88);vp_require(elements>0 && elements<=16777216,"invalid convolution workspace");workspace_conv=pb_max(workspace_conv,elements*4);}if load64(entry+104)&1 {let t=vp_at(vp_nodes,i);workspace_a=pb_max(workspace_a,load64(load64(t+32)+8)*4);if load64(t+40) {workspace_b=pb_max(workspace_b,load64(load64(t+40)+8)*4);}}i=i+1;}
    if workspace_a || workspace_conv {vp_plan_before=alloc(count*16);}
    if workspace_conv {vp_plan_workspace_conv=vp_buffer(workspace_conv);}
    if workspace_a {vp_math_mode="fp32-tc";vp_plan_range_host=alloc(8);vp_plan_range=vp_buffer(8);vp_upload(vp_plan_range,vp_plan_range_host,8);vp_plan_workspace_a=vp_buffer(workspace_a);if workspace_b {vp_plan_workspace_b=vp_buffer(workspace_b);}let suffix=".ptx";if vp_backend==3 {suffix=".cubin";}vp_require(vp_backend==2 || vp_backend==3,"tensor-core schedule requires CUDA/SM75");let image=vp_map(vp_path(vp_kernel_root,vp_suffix("pack",suffix)));let size=vp_bytes;let module=device_module(image);vp_require(module,device_error());pack=device_function(module,"flex_kernel");vp_require(pack,device_error());syscall(11,image,size,0,0,0,0);}
    i=0;
    while i<count {let entry=plan+80+i*128;let t=vp_at(vp_nodes,i);let skip=load64(entry+96);vp_require(skip==0 || skip==1,"invalid schedule skip");
        if skip {store64(t+120,0);}else if load8(entry) {
            vp_require(!load8(entry+63),"unterminated kernel name");let output=load64(entry+64);let threads=load64(entry+72);let work=load64(entry+80);let shared=load64(entry+88);
            vp_require(output>=i && output<count && threads>=32 && threads<=1024 && work>0 && work<=2147483647 && shared>=0 && shared<=49152,"invalid scheduled launch");
            let function=0;let j=0;while j<load64(names) {if pl_equal(vp_at(names,j),entry) {function=vp_at(functions,j);}j=j+1;}
            if !function {let suffix=".ptx";if vp_backend==1 {suffix=".hip";}if vp_backend==3 {suffix=".cubin";}let image=vp_map(vp_path(vp_kernel_root,vp_suffix(entry,suffix)));let size=vp_bytes;let module=device_module(image);vp_require(module,device_error());syscall(11,image,size,0,0,0,0);function=device_function(module,"flex_kernel");vp_require(function,device_error());h_add(names,entry);h_add(functions,function);}
            let args=load64(t+104);store64(load64(args+8),load64(vp_at(vp_nodes,output)));store64(load64(args+16),work);store64(t+120,function);
            if load64(entry+104)&8 {
                let source=(load64(entry+104)>>32)-1;vp_require(source>=0 && source<i,"invalid residual dependency");let residual=vp_at(vp_nodes,source);vp_require(load64(residual+8)==load64(t+8),"residual tensor size differs");store64(load64(args+80),load64(residual));
            }
            if load64(entry+104)&4 {
                let suffix=".ptx";if vp_backend==1 {suffix=".hip";}if vp_backend==3 {suffix=".cubin";}
                let image=vp_map(vp_path(vp_kernel_root,vp_suffix(vp_suffix(entry,"-input"),suffix)));let size=vp_bytes;let module=device_module(image);vp_require(module,device_error());syscall(11,image,size,0,0,0,0);let prepare=device_function(module,"flex_kernel");vp_require(prepare,device_error());
                let m=vp_host_metadata+i*192;let elements=load64(m+64)*load64(m+104)*load64(m+160)*load64(m+160)*load64(m+80)*load64(m+88);
                store64(vp_plan_before+i*16,vp_plan_prepare(prepare,load64(load64(t+32)),vp_plan_workspace_conv,elements));store64(load64(args+24),vp_plan_workspace_conv);
            }
            if load64(entry+104)&1 {
                let source=load64(t+32);let input=vp_plan_pack(pack,load64(source),vp_plan_workspace_a,load64(source+8));store64(vp_plan_before+i*16,input);store64(load64(args),vp_plan_workspace_a);
                if load64(t+24)==12 {let m=vp_host_metadata+i*192;let elements=load64(m+72)*(load64(m+104)/load64(m+184))*load64(m+160)*load64(m+160);let packed=vp_buffer(elements*4);let channels=0;let spatial=0;if load64(entry+104)&2 {channels=load64(m+104)/load64(m+184);spatial=load64(m+160)*load64(m+160);}vp_plan_pack_launch(vp_plan_pack_layout(pack,load64(t+48),packed,elements,channels,spatial));vp_check(device_stream_wait(vp_stream));vp_plan_range_check();store64(load64(args+32),packed);}
                else {let other=load64(t+40);store64(vp_plan_before+i*16+8,vp_plan_pack(pack,load64(other),vp_plan_workspace_b,load64(other+8)));store64(load64(args+24),vp_plan_workspace_b);}
            }
            store64(t+112,device_config((work+threads-1)/threads,1,1,threads,1,1,shared,vp_stream));vp_require(load64(t+112),device_error());
        }i=i+1;
    }vp_bytes=old_size;return 1;
}
