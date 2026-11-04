// Native CPU probe appended to a private trainer copy. The test substitutes
// an early return after ptj_send so no device, graph or optimizer is launched.
fn main(argc,argv) {
    vc_require(argc==3,"need journal output path and test mode");vc_init(argc,argv);
    let mode=pl_integer(load64(argv+16),pl_size(load64(argv+16)));vp_require(!pl_bad_number,"bad test mode");
    pt_length=1;pt_batch=2;pt_image_bytes=4;pt_row_bytes=56;pt_record_size=60;
    pt_data=alloc(32+1031*pt_record_size);pb_zero(pt_data,32+1031*pt_record_size);
    pt_batch_images=alloc(8);pt_batch_proprio=alloc(56);pt_batch_targets=alloc(32);pt_batch_phase_masks=alloc(8);
    pt_mirror_mask_host=alloc(8);pt_mirror_augment=1;pt_mirror_active=0;
    pt_memcpy=ffi_symbol(ffi_open("libc.so.6"),"memcpy");vp_require(pt_memcpy,"memcpy unavailable");
    pm_rng=(7120000^0x5a5a5a5a)&2147483647;
    let order=alloc(1031*8);let i=0;while i<935 {store64(order+i*8,(i*7)%935);i=i+1;}while i<1031 {store64(order+i*8,i);i=i+1;}
    // Initial/validation batch traffic must not create a training journal.
    pt_batch_fill(order,0,2);pt_batch_send();vp_require(syscall(21,load64(argv+8),0,0,0,0,0)!=0,"inactive journal created a file");
    ptj_begin(load64(argv+8),7120000,1031,935,1);pt_mirror_active=1;let start=0;
    while start<935 {
        let count=pb_min(2,935-start);if pt_prefetched!=start {pt_batch_fill(order,start,count);}pt_prefetched=-1;
        if mode==1 && start==2 {store64(pt_mirror_mask_host,load64(pt_mirror_mask_host)^1);}
        pt_batch_send();if mode==2 && !start {pt_batch_send();}
        let next=start+2;if next<935 {pt_prefetch_order=order;pt_prefetch_start=next;pt_prefetch_count=pb_min(2,935-next);pt_prefetch();}
        start=next;
    }
    if mode!=3 {ptj_finish();pt_mirror_active=0;pt_batch_fill(order,935,2);pt_batch_send();}return 0;
}
