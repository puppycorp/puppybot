import "../control/actions.flex";
import "../control/loss.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2,"visual-control-actions NEW_OUTPUT");let output=vc_absolute(load64(argv+8));vc_mkdir(output);let logits=alloc(28);let action=alloc(8);let i=0;
    while i<7 {let j=0;while j<7 {pb_put32(logits+j*4,0xc1200000);j=j+1;}pb_put32(logits+i*4,0x41200000);vc_require(ca_decode(logits,action)==i,"categorical argmax chose the wrong joint action");
        let steering=0x3f19999a;if i%3==0 {steering=0xbf19999a;}if i%3==1 || i==6 {steering=0;}let speed=0xbf800000;if i<3 {speed=0x3f800000;}if i==6 {speed=0;}
        vc_require(pb_u32(action)==steering && pb_u32(action+4)==speed && ca_class(pb_read_float(action),pb_read_float(action+4))==i,"joint action table differs from oracle commands");i=i+1;
    }
    pb_zero(logits,28);vc_require(!ca_decode(logits,action),"categorical ties are not deterministic");pb_put32(logits+12,0x7fc00000);vc_require(ca_decode(logits,action)<0,"nonfinite logits were accepted");
    vc_require(ca_class(0,vc_number(9,10))<0 && ca_class(vc_number(3,10),PB_ONE)<0,"unsupported continuous teacher targets were silently quantized");
    pb_zero(logits,28);pb_put32(logits,pb_f64_to_f32(f64_from_i64(-1000)));pb_put32(logits+4,pb_f64_to_f32(f64_from_i64(1000)));pb_put32(action,0xbf19999a);pb_put32(action+4,0x3f800000);let seeds=alloc(28);
    let loss=pt_categorical_loss(logits,action,PB_ONE,vc_number(1,2),seeds);vc_require(f64_lt(f64_magnitude(f64_sub(loss,f64_from_i64(1000))),vc_number(1,1000000000)) && pb_u32(seeds)==0xbf000000 && pb_u32(seeds+4)==0x3f000000,"categorical loss is unstable for extreme logits");
    pb_put32(action,pb_f64_to_f32(vc_number(3,10)));loss=pt_categorical_loss(logits,action,0,0,seeds);vc_require(!loss,"masked categorical target contributes loss");i=0;while i<7 {vc_require(!f64_magnitude(pb_read_float(seeds+i*4)),"masked categorical target contributes gradient");i=i+1;}
    loss=pt_binary_loss(f64_from_i64(1000),0,vc_number(1,2),seeds);vc_require(f64_eq(loss,f64_from_i64(500)) && pb_u32(seeds)==0x3f000000,"positive extreme event logit is unstable");loss=pt_binary_loss(f64_from_i64(-1000),PB_ONE,PB_ONE,seeds);vc_require(f64_eq(loss,f64_from_i64(1000)) && pb_u32(seeds)==0xbf800000,"negative extreme event logit is unstable");
    let targets=alloc(6*16);i=0;while i<6 {pb_put32(targets+i*16+12,0x3f800000);i=i+1;}pb_put32(targets+2*16+8,0x3f800000);pb_put32(targets+4*16+8,0x3f800000);pb_put32(targets+5*16+8,0x3f800000);
    vc_require(!pt_event_label(targets,0,2) && pt_event_label(targets,2,2)==PB_ONE && !pt_event_label(targets,4,2) && pt_event_label(targets,5,2)==PB_ONE,"event labels mix batch histories or shift the detection frame");vc_require(f64_eq(pt_event_weight(targets,2,2),f64_from_i64(50)),"positive camera event weight differs");
    pb_put32(targets+12,0);vc_require(!pt_event_mask(targets,0,2) && !pt_event_mask(targets,2,2),"masked predecessor phase contributes event supervision");pb_put32(targets+8,0x3f800000);vc_require(!pt_event_weight(targets,2,2),"unknown predecessor label changes event supervision");
    loss=pt_binary_loss(f64_from_i64(1000),PB_ONE,0,seeds);vc_require(!loss && !pb_read_float(seeds),"masked event contributes loss or gradient");
    vc_require(!pt_phase_mask(0,0x3f800000,1,0) && pt_phase_mask(0,0x3f800000,1,1)==0x3f800000,"phase supervision policy ignores burn-in validity");
    vc_require(!pt_phase_mask(0,0,1,1) && !pt_phase_mask(0x3f800000,0x3f800000,0,1) && !pt_phase_mask(0x3f800000,0x3f800000,0,0),"padding or inactive batch item contributes phase supervision");
    vc_save_text(vc_path(output,"result.json"),"{\"passed\":true,\"runtime\":\"Flexscript\",\"classes\":7,\"oneJointActionChosen\":true,\"nonfiniteLogitsRejected\":true,\"unsupportedTargetsRejected\":true,\"stableCrossEntropyChecked\":true,\"maskedTargetsProduceNoLossOrGradient\":true,\"eventLabelsAlignedPerHistory\":true,\"maskedPredecessorsExcluded\":true,\"stableEventLossChecked\":true}\n");pl_print(1,"Native categorical action codec and loss passed.\n");return 0;
}
