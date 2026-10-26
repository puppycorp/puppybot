import "workflow.flex";
import "verify.flex";
global vw_run_input=0;
fn vw_usage() {
    pl_print(1,"Visual control (native Flexscript)\n  flex/control.sh build\n");
    pl_print(1,"  flex/control.sh test [NEW_OUTPUT_DIRECTORY]\n");
    pl_print(1,"  flex/control.sh collect --output DIR [--episodes 64 --validation 8 --seed 101000]\n");
    pl_print(1,"  flex/control.sh train --data FILE --output DIR [--epochs 80 --batch 4 --learning-rate-micros 700 --from-scratch]\n");
    pl_print(1,"  flex/control.sh init --output DIR [--seed 7]\n");
    pl_print(1,"  flex/control.sh run --policy DIR --output DIR [--episodes 8 --seed 110000 --horizon 150 --blackout --hidden-target --scene DIR]\n");
    pl_print(1,"  flex/control.sh verify --run EPISODE_DIR --policy POLICY_DIR --output DIR [--blackout]\n");
    pl_print(1,"\nThe shared simulator robot asset must already exist. No Python runs in this workflow.\n");return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);if argc<2 {return vw_usage();}let command=load64(argv+8);if pl_equal(command,"--help") || pl_equal(command,"help") {return vw_usage();}
    vw_root=vc_absolute(".");if pl_equal(command,"collect") {vw_seed=101000;vw_episodes=64;}if pl_equal(command,"init") || pl_equal(command,"train") {vw_seed=7;}
    let i=2;while i<argc {
        let flag=load64(argv+i*8);
        if pl_equal(flag,"--from-scratch") {vw_random=1;}
        else if pl_equal(flag,"--blackout") {vw_blackout=1;}
        else if pl_equal(flag,"--hidden-target") {vw_hidden=1;}
        else {
            i=i+1;vc_require(i<argc,"missing option value");let value=load64(argv+i*8);
            if pl_equal(flag,"--output") {vw_output=vc_absolute(value);}
            else if pl_equal(flag,"--policy") || pl_equal(flag,"--initial-policy") {vw_policy=vc_absolute(value);}
            else if pl_equal(flag,"--scene") {vw_scene=vc_absolute(value);}
            else if pl_equal(flag,"--data") {vw_data=vc_absolute(value);}
            else if pl_equal(flag,"--run") {vw_run_input=vc_absolute(value);}
            else {
                let n=pl_integer(value,pl_size(value));vc_require(!pl_bad_number && n>=0,"invalid numeric option");
                if pl_equal(flag,"--seed") {vc_require(n<=2147483647,"seed exceeds native RNG range");vw_seed=n;}
                else if pl_equal(flag,"--episodes") {vc_require(n>=1 && n<=64,"episodes must be in 1..64");vw_episodes=n;}
                else if pl_equal(flag,"--validation") {vw_validation=n;}
                else if pl_equal(flag,"--horizon") {vc_require(n>=1 && n<=1000,"horizon must be in 1..1000");vw_horizon=n;}
                else if pl_equal(flag,"--epochs") {vc_require(n<=10000,"epoch limit exceeded");vw_epochs=n;}
                else if pl_equal(flag,"--batch") {vc_require(n>=1 && n<=8,"batch must be in 1..8");vw_batch=n;}
                else if pl_equal(flag,"--learning-rate-micros") {vc_require(n>=1 && n<=10000,"learning rate must be in 1..10000 millionths");vw_rate=n;}
                else {vc_require(0,vc_concat("unknown option ",flag));}
            }
        }i=i+1;
    }
    vc_require(vw_output,"--output DIRECTORY is required");
    if pl_equal(command,"train") || pl_equal(command,"init") {return vw_train(pl_equal(command,"init"));}
    ve_open_buffers();if pl_equal(command,"collect") {return vw_collect();}if pl_equal(command,"run") {return vw_run();}
    if pl_equal(command,"verify") {vc_require(vw_run_input && vw_policy,"verify requires --run EPISODE_DIRECTORY and --policy DIRECTORY");return va_verify(vw_run_input,vw_policy,vw_output,vw_blackout);}
    vc_require(0,"unknown visual-control command");return 2;
}
