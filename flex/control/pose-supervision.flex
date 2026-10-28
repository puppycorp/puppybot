// Checked, pre-action relative-motion targets used only by the training loss.
import "dataset.flex";
global pt_pose_data=0;
fn pt_pose_open(directory,data,bytes,row_bytes) {
    let n=load64(data+8);let fit=load64(data+16);let length=load64(data+24);let receipt=vc_json_file(vc_path(directory,"receipt.json"));
    vc_require(pj_boolean(receipt,"passed") && pj_boolean(receipt,"verifiedAgainstPhysicalTrace") && pj_boolean(receipt,"actorInputsUnchanged") && vc_json_int(receipt,"normalizationMetres",0)==8 && vc_json_int(receipt,"episodes",0)==n && vc_json_int(receipt,"fittingHistories",0)==fit && vc_json_int(receipt,"validationHistories",0)==n-fit && vc_json_int(receipt,"sequenceLength",0)==length && pl_equal(pj_string_field(receipt,"sourceDataSHA256"),vc_digest(data,bytes)),"memory-pose receipt does not match demonstration data");
    let expected=vc_string(pj_string_field(receipt,"targetsSHA256"));pt_pose_data=vc_map(vc_path(directory,"targets.bin"));let pose_bytes=vc_size;
    vc_require(pose_bytes==32+n*length*20 && load64(pt_pose_data)==load64("PVPOSE01") && load64(pt_pose_data+8)==n && load64(pt_pose_data+16)==fit && load64(pt_pose_data+24)==length && pl_equal(vc_digest(pt_pose_data,pose_bytes),expected),"memory-pose target hash or dimensions differ");
    let episode=0;while episode<n {let base=data+32+episode*length*(21168+row_bytes);let t=0;while t<length {let source=base+length*21168+t*row_bytes;let target=pt_pose_data+32+(episode*length+t)*20;let valid=vd_valid_word(source,row_bytes);vc_require(pb_u32(target+16)==valid && (valid==0 || valid==0x3f800000),"memory-pose mask differs from valid frame");
            let i=0;while i<4 {let value=pb_read_float(target+i*4);vc_require(f64_is_finite(value) && f64_le(f64_magnitude(value),PB_ONE),"invalid normalized memory-pose target");if !valid {vc_require(!pb_u32(target+i*4),"memory-pose padding is nonzero");}i=i+1;}
            if valid {let sine=pb_read_float(target+8);let cosine=pb_read_float(target+12);vc_require(f64_lt(f64_magnitude(f64_sub(f64_add(f64_mul(sine,sine),f64_mul(cosine,cosine)),PB_ONE)),vc_number(1,10000)),"memory-pose heading is not a unit vector");if !t {vc_require(!f64_magnitude(pb_read_float(target)) && !f64_magnitude(pb_read_float(target+4)) && !f64_magnitude(sine) && f64_eq(cosine,PB_ONE),"memory-pose initial frame is not the origin");}}
            t=t+1;}episode=episode+1;}
    return 0;
}
