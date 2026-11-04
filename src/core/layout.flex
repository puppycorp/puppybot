// Allocation layout. Optional values carry an explicit presence word.
// Joint: 32 words. Arm: header, wheel acknowledgements, four joints, scratch.
import "words.flex";

global PB_J_ID = 0;
global PB_J_MIN = 1;
global PB_J_MAX = 2;
global PB_J_RAW_MIN = 3;
global PB_J_RAW_MAX = 4;
global PB_J_SIGN = 5;
global PB_J_DRIVE_SIGN = 6;
global PB_J_REFERENCE_TICK = 7;
global PB_J_REFERENCE_ANGLE = 8;
global PB_J_ZERO_OFFSET = 9;
global PB_J_ONLINE = 10;
global PB_J_FEEDBACK = 11;
global PB_J_TICK_VALID = 12;
global PB_J_TICK = 13;
global PB_J_ANGLE_VALID = 14;
global PB_J_ANGLE = 15;
global PB_J_TARGET_VALID = 16;
global PB_J_TARGET = 17;
global PB_J_TARGET_ANGLE_VALID = 18;
global PB_J_TARGET_ANGLE = 19;
global PB_J_DELTA = 20;
global PB_J_LIMIT_ENABLED = 21;
global PB_J_SPEED = 22;
global PB_J_LAST_FEEDBACK = 23;
global PB_J_TEMP_VALID = 24;
global PB_J_TEMP = 25;
global PB_J_SENT_VALID = 26;
global PB_J_SENT_SPEED = 27;
global PB_J_LAST_SPEED_CMD = 28;
global PB_J_STALL_VALID = 29;
global PB_J_STALL_SINCE = 30;
global PB_J_FAULT = 31;
global PB_A_SPEED = 0;
global PB_A_LAST_CMD = 1;
global PB_A_LAST_OK = 2;
global PB_A_ERROR = 3;
global PB_A_MODE = 4;
global PB_A_INITIALIZED = 5;
global PB_A_FRAME = 6;
global PB_A_OVERRIDE_VALID = 7;
global PB_A_OVERRIDE_SPEED = 8;
global PB_A_LAST_STEP = 9;
global PB_A_DX = 10;
global PB_A_DY = 11;
global PB_A_DZ = 12;
global PB_A_YAW = 13;
global PB_A_SHOULDER = 14;
global PB_A_ELBOW = 15;
global PB_A_WRIST = 16;
global PB_A_X = 17;
global PB_A_Y = 18;
global PB_A_Z = 19;
global PB_A_PITCH = 20;

fn pb_joint(arm, index) { return arm + 512 + index * 256; }
fn pb_j(joint, field) { return load64(joint + field * 8); }
fn pb_js(joint, field, value) { store64(joint + field * 8, value); return value; }
fn pb_a(arm, field) { return load64(arm + field * 8); }
fn pb_as(arm, field, value) { store64(arm + field * 8, value); return value; }
fn pb_wheel_ready(arm, index) { return arm + 168 + index * 8; }
fn pb_wheel_id(arm, index) { return arm + 200 + index * 8; }
fn pb_wheel_attempt(arm, index) { return arm + 232 + index * 8; }
