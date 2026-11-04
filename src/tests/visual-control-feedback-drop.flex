import "../control/augmentation.flex";
fn main(argc,argv) {
    vc_init(argc,argv);if argc>1 {pf_mask(2,3,250);return 0;}
    pf_rng=123;let before=pm_rng;vc_require(!pf_mask(4,3,0),"zero drop rate masked feedback");vc_require(pf_mask(4,3,1000)==7,"full drop rate did not mask every active sequence");vc_require(pm_rng==before,"feedback mask changed the mirror random stream");
    pf_rng=202;let a=pf_mask(4,3,250);pf_rng=202;let b=pf_mask(4,3,250);vc_require(a==b && !(a&8),"feedback mask is nondeterministic or selected an inactive sequence");
    pf_rng=77;let selected=0;let sample=0;while sample<10000 {if pf_mask(1,1,250) {selected=selected+1;}sample=sample+1;}vc_require(selected>2200 && selected<2800,"feedback mask frequency differs substantially from its requested rate");
    let own=alloc(28);let copy=alloc(28);let i=0;while i<7 {pb_put32(own+i*4,0x3f800000);i=i+1;}pb_put32(own+24,0);vc_copy(copy,own,28);pf_neutral_drive(copy);
    i=0;while i<5 {vc_require(!pb_u32(copy+i*4) && pb_u32(own+i*4)==0x3f800000,"feedback masking did not preserve the source");i=i+1;}
    vc_require(pb_u32(copy+20)==0x3f800000 && !pb_u32(copy+24),"feedback masking changed contact or event feedback");
    pl_print(1,"Feedback dropout masks, determinism and contact preservation passed.\n");return 0;
}
