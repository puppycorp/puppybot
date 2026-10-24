// Build-only Pup -> native factory adapter. No Python model execution.
import "../../../flexscript/libs/ml/pup/parser.flex";
fn main(argc,argv) {
    if argc!=3 {pg_print("Usage: compile-pup MODEL.pup OUTPUT.flex\n");return 2;}
    let path=load64(argv+8);let fd=syscall(2,path,0,0,0,0,0);if fd<0 {return 1;}
    let text=alloc(262145);let used=0;let n=1;
    while n>0 && used<262144 {n=syscall(0,fd,text+used,262144-used,0,0,0);if n>0 {used=used+n;}}
    syscall(3,fd,0,0,0,0,0);if n<0 || used==262144 {return 1;}
    pup_parse_inference(text,used,path);let source=pn_lower_host("pup_build_detector");
    let crypto=ffi_open("libcrypto.so.3");if !crypto {return 1;}let sha=ffi_symbol(crypto,"SHA256");if !sha {return 1;}let digest=alloc(32);ffi_call(sha,text,used,digest,0,0,0);let hex="0123456789abcdef";let hash=alloc(65);let i=0;while i<32 {let v=load8(digest+i);store8(hash+i*2,load8(hex+(v>>4)));store8(hash+i*2+1,load8(hex+(v&15)));i=i+1;}
    pn_emit("fn pup_detector_source_hash(){return \"");pn_emit(hash);pn_emit("\";}\n");
    fd=syscall(2,load64(argv+16),577,420,0,0,0);if fd<0 {return 1;}let at=0;
    while at<pn_length {n=syscall(1,fd,source+at,pn_length-at,0,0,0);if n<=0 {return 1;}at=at+n;}
    syscall(3,fd,0,0,0,0,0);return 0;
}
