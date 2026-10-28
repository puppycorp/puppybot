import "workflow.flex";
import "correction.flex";
import "verify.flex";
import "chase.flex";
global vw_run_input=0;
fn vw_usage() {
    pl_print(1,"Visual control (native Flexscript)\n  flex/control.sh build\n");
    pl_print(1,"  flex/control.sh test [NEW_OUTPUT_DIRECTORY]\n");
    pl_print(1,"  flex/control.sh collect --output DIR [--episodes 64 --validation 8 --seed 101000 --horizon 300 --curriculum mixed|easy|hidden --scene DIR]\n");
    pl_print(1,"  flex/control.sh train --data FILE --output DIR [--epochs 80 --batch 2 --learning-rate-micros 700 --from-scratch --categorical --phase-gated --balanced-phase --return-weight-milli WEIGHT --contact-weight-milli WEIGHT --drop-drive-feedback-milli RATE --event-aux --memory-pose DIR --target-position DIR|--target-heatmap DIR --heat-actor --heat-stop-gradient --heat-absence --phase-from-valid --mirror-augment --stop-weight-one --checkpoint-every 10 --large-model --focus-history INDEX --focus-copies COUNT --max-optimizer-steps COUNT --reversal-penalty-milli WEIGHT --phase-consistency-milli WEIGHT]\n");
    pl_print(1,"  flex/control.sh collect --chase --scene-catalog DIR --output DIR [--episodes 128 --validation 8 --seed 101000 --horizon 300 --lean --wheel-odometry]\n");
    pl_print(1,"  flex/control.sh run --chase (--policy DIR | --chase-forward) --scene-catalog DIR --output DIR [--episodes 16 --seed 110000 --horizon 300 --blackout --large-model --lean --wheel-odometry]\n");
    pl_print(1,"  flex/control.sh init --output DIR [--seed 7]\n");
    pl_print(1,"  flex/control.sh run --policy DIR --output DIR [--episodes 8 --seed 110000 --horizon 150 --blackout --hidden-target --scene DIR --image-128 --large-model]\n");
    pl_print(1,"  flex/control.sh verify --run EPISODE_DIR --policy POLICY_DIR --output DIR [--blackout --image-128 --large-model]\n");
    pl_print(1,"  flex/control.sh verify-data --run COLLECTION_DIR --data FILE --output DIR [--audit-start 0 --audit-count EPISODES --large-model --allow-incomplete]\n");
    pl_print(1,"  flex/control.sh pack-data --data FILE --output DIR\n");
    pl_print(1,"  flex/control.sh correct --policy DIR --output DIR [--episodes 16 --validation 4 --rollin 30 --rollin-min 0 --horizon 300 --scene-catalog DIR --label-rollin --allow-incomplete --coverage-teacher --return-rollin --return-via-home --approach-side 0..3 --large-model]\n");
    pl_print(1,"\nThe shared simulator robot asset must already exist. No Python runs in this workflow.\n");return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);if argc<2 {return vw_usage();}let command=load64(argv+8);if pl_equal(command,"--help") || pl_equal(command,"help") {return vw_usage();}
    vw_root=vc_absolute(".");vw_curriculum="mixed";if pl_equal(command,"collect") {vw_seed=101000;vw_episodes=64;vw_horizon=300;}if pl_equal(command,"init") || pl_equal(command,"train") {vw_seed=7;}
    if pl_equal(command,"correct") {vw_seed=331000;vw_episodes=16;vw_validation=4;vw_horizon=300;}
    let i=2;while i<argc {
        let flag=load64(argv+i*8);
        if pl_equal(flag,"--from-scratch") {vw_random=1;}
        else if pl_equal(flag,"--categorical") {vw_categorical=1;}
        else if pl_equal(flag,"--phase-gated") {vw_categorical=1;vw_phase_gate=1;}
        else if pl_equal(flag,"--balanced-phase") {vc_require(!vw_balanced_phase,"duplicate balanced phase option");vw_balanced_phase=1;}
        else if pl_equal(flag,"--event-aux") {vw_event_aux=1;}
        else if pl_equal(flag,"--heat-actor") {vc_require(!vw_heat_actor,"duplicate heat-actor option");vw_heat_actor=1;}
        else if pl_equal(flag,"--heat-stop-gradient") {vc_require(!vw_heat_stop_gradient,"duplicate heat-stop-gradient option");vw_heat_stop_gradient=1;}
        else if pl_equal(flag,"--heat-absence") {vc_require(!vw_heat_absence,"duplicate heat-absence option");vw_heat_absence=1;}
        else if pl_equal(flag,"--phase-from-valid") {vc_require(!vw_phase_from_valid,"duplicate phase supervision option");vw_phase_from_valid=1;}
        else if pl_equal(flag,"--mirror-augment") {vc_require(!vw_mirror_augment,"duplicate mirror augmentation option");vw_mirror_augment=1;}
        else if pl_equal(flag,"--stop-weight-one") {vc_require(!vw_stop_weight_one,"duplicate stop weight option");vw_stop_weight_one=1;}
        else if pl_equal(flag,"--blackout") {vw_blackout=1;}
        else if pl_equal(flag,"--image-128") {vc_require(ve_image_side==84,"duplicate image resolution option");ve_image_side=128;ve_image_bytes=49152;}
        else if pl_equal(flag,"--large-model") {vc_require(!vw_large_model,"duplicate large-model option");vw_large_model=1;ve_memory_width=256;}
        else if pl_equal(flag,"--hidden-target") {vw_hidden=1;}
        else if pl_equal(flag,"--chase") {vw_chase=1;}
        else if pl_equal(flag,"--chase-forward") {vw_chase=1;vw_chase_forward=1;}
        else if pl_equal(flag,"--lean") {vc_require(!ve_lean,"duplicate lean option");ve_lean=1;}
        else if pl_equal(flag,"--wheel-odometry") {vc_require(!ve_wheel_odometry,"duplicate wheel odometry option");ve_wheel_odometry=1;}
        else if pl_equal(flag,"--label-rollin") {vw_label_rollin=1;}
        else if pl_equal(flag,"--allow-incomplete") {vc_require(!vw_allow_incomplete,"duplicate incomplete-data option");vw_allow_incomplete=1;va_allow_incomplete=1;}
        else if pl_equal(flag,"--coverage-teacher") {vc_require(!vw_coverage_teacher,"duplicate coverage teacher option");vw_coverage_teacher=1;}
        else if pl_equal(flag,"--return-rollin") {vc_require(!vw_return_rollin,"duplicate return roll-in option");vw_return_rollin=1;}
        else if pl_equal(flag,"--return-via-home") {vw_correction_waypoint=1;}
        else {
            i=i+1;vc_require(i<argc,"missing option value");let value=load64(argv+i*8);
            if pl_equal(flag,"--output") {vw_output=vc_absolute(value);}
            else if pl_equal(flag,"--policy") || pl_equal(flag,"--initial-policy") {vw_policy=vc_absolute(value);}
            else if pl_equal(flag,"--scene") {vw_scene=vc_absolute(value);}
            else if pl_equal(flag,"--scene-catalog") {vw_catalog=vc_absolute(value);}
            else if pl_equal(flag,"--data") {vw_data=vc_absolute(value);}
            else if pl_equal(flag,"--memory-pose") {vc_require(!vw_pose_targets,"duplicate memory-pose directory");vw_pose_targets=vc_absolute(value);}
            else if pl_equal(flag,"--target-position") {vc_require(!vw_target_positions,"duplicate target-position directory");vw_target_positions=vc_absolute(value);}
            else if pl_equal(flag,"--target-heatmap") {vc_require(!vw_target_positions,"duplicate target-position directory");vw_target_positions=vc_absolute(value);vw_target_heatmap=1;}
            else if pl_equal(flag,"--run") {vw_run_input=vc_absolute(value);}
            else if pl_equal(flag,"--curriculum") {vc_require(pl_equal(value,"mixed") || pl_equal(value,"easy") || pl_equal(value,"hidden"),"curriculum must be mixed, easy or hidden");vw_curriculum=value;}
            else {
                let n=pl_integer(value,pl_size(value));vc_require(!pl_bad_number && n>=0,"invalid numeric option");
                if pl_equal(flag,"--seed") {vc_require(n<=2147483647,"seed exceeds native RNG range");vw_seed=n;}
                else if pl_equal(flag,"--episodes") {vc_require(n>=1 && n<=128,"episodes must be in 1..128");vw_episodes=n;}
                else if pl_equal(flag,"--validation") {vw_validation=n;}
                else if pl_equal(flag,"--rollin") {vc_require(n<=511,"rollin exceeds 511 actions");vw_rollin=n;}
                else if pl_equal(flag,"--rollin-min") {vc_require(n<=511,"minimum rollin exceeds 511 actions");vw_rollin_min=n;}
                else if pl_equal(flag,"--approach-side") {vc_require(n<=3,"approach side must be in 0..3");vw_correction_start_side=n;}
                else if pl_equal(flag,"--audit-start") {vc_require(n<=1023,"audit start exceeds 1023");va_audit_start=n;}
                else if pl_equal(flag,"--audit-count") {vc_require(n>=1 && n<=1024,"audit count must be in 1..1024");va_audit_count=n;}
                else if pl_equal(flag,"--horizon") {vc_require(n>=1 && n<=1000,"horizon must be in 1..1000");vw_horizon=n;}
                else if pl_equal(flag,"--epochs") {vc_require(n<=10000,"epoch limit exceeded");vw_epochs=n;}
                else if pl_equal(flag,"--checkpoint-every") {vc_require(n>=1 && n<=10000 && !vw_checkpoint_every,"invalid or duplicate checkpoint interval");vw_checkpoint_every=n;}
                else if pl_equal(flag,"--batch") {vc_require(n>=1 && n<=8,"batch must be in 1..8");vw_batch=n;}
                else if pl_equal(flag,"--learning-rate-micros") {vc_require(n>=1 && n<=10000,"learning rate must be in 1..10000 millionths");vw_rate=n;}
                else if pl_equal(flag,"--focus-history") {vc_require(vw_focus_history<0 && n<=1023,"duplicate or invalid focus-history option");vw_focus_history=n;}
                else if pl_equal(flag,"--focus-copies") {vc_require(!vw_focus_copies && n>=1 && n<=1024,"duplicate or invalid focus-copies option");vw_focus_copies=n;}
                else if pl_equal(flag,"--max-optimizer-steps") {vc_require(!vw_max_optimizer_steps && n>=1 && n<=100000000,"duplicate or invalid optimizer step limit");vw_max_optimizer_steps=n;}
                else if pl_equal(flag,"--reversal-penalty-milli") {vc_require(!vw_reversal_milli && n>=1 && n<=10000,"duplicate or invalid reversal penalty");vw_reversal_milli=n;}
                else if pl_equal(flag,"--return-weight-milli") {vc_require(!vw_return_weight_milli && n>=1000 && n<=10000,"duplicate or invalid return control weight");vw_return_weight_milli=n;}
                else if pl_equal(flag,"--contact-weight-milli") {vc_require(!vw_contact_weight_milli && n>=1000 && n<=10000,"duplicate or invalid contact control weight");vw_contact_weight_milli=n;}
                else if pl_equal(flag,"--drop-drive-feedback-milli") {vc_require(!vw_feedback_drop_milli && n>=1 && n<=1000,"duplicate or invalid drive feedback drop rate");vw_feedback_drop_milli=n;}
                else if pl_equal(flag,"--phase-consistency-milli") {vc_require(!vw_phase_consistency_milli && n>=1 && n<=10000,"duplicate or invalid phase consistency penalty");vw_phase_consistency_milli=n;}
                else {vc_require(0,vc_concat("unknown option ",flag));}
            }
        }i=i+1;
    }
    vc_require(vw_output,"--output DIRECTORY is required");
    vc_require(ve_image_side==84 || pl_equal(command,"run") || pl_equal(command,"verify"),"128x128 is only supported for policy run and verify");
    vc_require(!vw_large_model || (ve_image_side==84 && (pl_equal(command,"train") || pl_equal(command,"run") || pl_equal(command,"verify") || pl_equal(command,"correct") || pl_equal(command,"verify-data"))),"large model requires an 84x84 train, run, verify, correct or verify-data command");
    vc_require(!vw_mirror_augment || pl_equal(command,"train"),"mirror augmentation is training-only");
    vc_require(!vw_chase || pl_equal(command,"collect") || pl_equal(command,"run"),"the chase game is only valid for collect and run");
    vc_require(!vw_chase_forward || pl_equal(command,"run"),"the always-forward chase baseline is only valid for run");
    vc_require(!ve_lean || pl_equal(command,"collect") || pl_equal(command,"run"),"lean recording is only valid for collect and run");
    vc_require(!ve_wheel_odometry || vw_chase,"wheel-only odometry is only valid for the chase game");
    vc_require(!vw_stop_weight_one || pl_equal(command,"train"),"stop weight is training-only");
    vc_require((vw_focus_history<0 && !vw_focus_copies) || (pl_equal(command,"train") && vw_focus_history>=0 && vw_focus_copies>=1),"focus requires --focus-history and --focus-copies during training");
    vc_require(!vw_max_optimizer_steps || pl_equal(command,"train"),"max optimizer steps is only valid during training");
    vc_require(!vw_reversal_milli || pl_equal(command,"train"),"reversal penalty is only valid during training");
    vc_require(!vw_phase_consistency_milli || pl_equal(command,"train"),"phase consistency is only valid during training");
    vc_require(!vw_balanced_phase || pl_equal(command,"train"),"balanced phase loss is only valid during training");
    vc_require(!vw_return_weight_milli || pl_equal(command,"train"),"return control weight is only valid during training");
    vc_require(!vw_contact_weight_milli || pl_equal(command,"train"),"contact control weight is only valid during training");
    vc_require(!vw_feedback_drop_milli || pl_equal(command,"train"),"drive feedback dropout is only valid during training");
    vc_require(!vw_allow_incomplete || pl_equal(command,"correct") || pl_equal(command,"verify-data"),"incomplete-data opt-in is only valid for correction collection or data verification");
    vc_require(!vw_coverage_teacher || pl_equal(command,"correct"),"coverage teacher is only valid for correction collection");
    vc_require(!vw_pose_targets || pl_equal(command,"train"),"memory-pose supervision is training-only");
    vc_require(!vw_target_positions || pl_equal(command,"train"),"target-position supervision is training-only");
    vc_require(!vw_heat_actor || (pl_equal(command,"train") && vw_target_heatmap && vw_target_positions),"heat-actor requires target-heatmap training");
    vc_require(!vw_heat_stop_gradient || vw_heat_actor,"heat-stop-gradient requires a heat actor");
    vc_require(!vw_heat_absence || (pl_equal(command,"train") && vw_target_heatmap && vw_target_positions),"heat-absence requires target-heatmap training");
    if pl_equal(command,"train") || pl_equal(command,"init") {return vw_train(pl_equal(command,"init"));}
    if pl_equal(command,"pack-data") {vc_require(vw_data,"pack-data requires --data FILE");return vd_pack(vw_data,vw_output);}
    ve_open_buffers();if vw_chase && pl_equal(command,"collect") {return vx_collect();}if vw_chase && pl_equal(command,"run") {return vx_run();}if pl_equal(command,"collect") {return vw_collect();}if pl_equal(command,"run") {return vw_run();}if pl_equal(command,"correct") {return vw_correct();}
    if pl_equal(command,"verify") {vc_require(vw_run_input && vw_policy,"verify requires --run EPISODE_DIRECTORY and --policy DIRECTORY");return va_verify(vw_run_input,vw_policy,vw_output,vw_blackout);}
    if pl_equal(command,"verify-data") {vc_require(vw_run_input && vw_data,"verify-data requires --run COLLECTION_DIRECTORY and --data FILE");return va_verify_data(vw_run_input,vw_data,vw_output);}
    vc_require(0,"unknown visual-control command");return 2;
}
