import "ops.flex";
fn gpu_launch_word(index) {return 0;}
fn kernel(index,input,output,count) {if index<count {pb_put32(output+index*4,vk_element(index,input,gpu_launch_word(0),gpu_launch_word(1),gpu_launch_word(2),gpu_launch_word(3)));}return 0;}
fn main() {return 78;}
