// Inventory generation allocates shapes only; weights are not needed at build time.
import "runtime.flex";
import "../../build/flex/detector-model.flex";
fn main(argc,argv) {
    pl_init();if argc!=2 {pl_print(2,"Usage: pup-describe OUTPUT.bin\n");return 2;}
    vp_init(".",0,0);vp_compile_only=1;pup_build_model();let data=vp_plan_inventory();return pl_atomic_file(load64(argv+8),data,load64(vp_nodes)*224);
}
