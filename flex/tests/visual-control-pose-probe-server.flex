// Synthetic raw actor server for pose-probe alignment tests.
import "../control/host.flex";
fn qs_write(data,bytes) {let done=0;while done<bytes {let n=syscall(1,3,data+done,bytes-done,0,0,0);if n<=0 {return 0;}done=done+n;}return 1;}
fn main(argc,argv) {
    vc_init(argc,argv);if !qs_write("VCR25601",8) {return 1;}let input=alloc((21168+7+256)*4);let output=alloc(263*4);pb_zero(output,263*4);pb_put32(output+4,0x3f800000);
    while 1 {let done=0;while done<(21168+7+256)*4 {let n=syscall(0,3,input+done,(21168+7+256)*4-done,0,0,0);if !n {if !done {return 0;}return 1;}if n<0 {return 1;}done=done+n;}if !qs_write(output,263*4) {return 1;}}
    return 0;
}
