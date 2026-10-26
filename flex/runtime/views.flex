// Declarative dashboard; controller state is shared with HTTP and wire clients.
fn pu_attr(value) { if value { return ""; } return 0; }
fn pu_number(value) { if value < 0 { return m_cat("-", m_int(-value)); } return m_int(value); }
fn pu_decimal(value) {
    let tenth = f64_to_i64_trunc(f64_mul(value, f64_from_i64(10))); let sign = "";
    if tenth < 0 { sign = "-"; tenth = -tenth; }
    return m_cat(m_cat(m_cat(sign, m_int(tenth / 10)), "."), m_int(tenth % 10));
}
fn pu_mode() { if pb_vget(pu_app, 8) { return "Fake bus"; } if pb_vget(pu_app, 40) { return "Simulator"; } return "Hardware"; }
fn pu_ready() {
    if !pb_vget(pu_app, 8) && load64(pb_vget(pu_app, 4)) < 0 { return 0; }
    if pb_vget(pu_app, 37) { return pb_vget(pu_app, 38) == 1 && pb_feedback_ready(pb_vget(pu_app, 1), pu_now); } return 1;
}
fn pu_state() {
    if !pb_vget(pu_app, 8) && load64(pb_vget(pu_app, 4)) < 0 { return "Disconnected"; }
    if !pb_vget(pu_app, 37) { return "Ready"; }
    if pb_vget(pu_app, 38) == 1 { return "Enabled"; } if pb_vget(pu_app, 38) == 2 { return "Stopping"; } return "Monitor";
}
fn pu_interlock() {
    if !pb_vget(pu_app, 37) { return "Temperature not measured"; }
    let reason = pb_vget(pu_app, 39);
    if reason == 1 { return "Temperature unavailable"; }
    if reason == 2 { return "Temperature feedback stale"; }
    if reason == 3 { return "Over temperature · outputs stopped"; }
    return "Temperature protection active";
}
fn pu_temperature(index) {
    if !pb_vget(pu_app, 37) { return "Not measured (fake)"; }
    let joint = pb_joint(load64(pu_app), index); let at = pb_vget(pb_vget(pu_app, 1), 12 + index);
    if !pb_j(joint, PB_J_TEMP_VALID) || at < 0 { return "Temperature unavailable"; }
    let text = m_cat(pu_number(pb_j(joint, PB_J_TEMP)), " °C");
    if pu_now < at || pu_now - at > 250 { return m_cat(text, " · stale"); } return m_cat(text, " · fresh");
}
fn pu_joint_status(joint) {
    if pb_j(joint, PB_J_FAULT) { return pb_fault_name(pb_j(joint, PB_J_FAULT)); }
    if !pb_j(joint, PB_J_ONLINE) || !pb_j(joint, PB_J_FEEDBACK) { return "No feedback"; }
    if !pb_j(joint, PB_J_LIMIT_ENABLED) { return "Limits disabled"; }
    if !pb_tick_within(joint, pb_j(joint, PB_J_TICK)) { return "At limit"; } return "Within limits";
}
fn pu_joint_status_class(joint) { if pb_j(joint, PB_J_FAULT) { return "joint-status error"; } return "joint-status"; }
fn pu_tick(joint) { if !pb_j(joint, PB_J_TICK_VALID) { return "—"; } return pu_number(pb_j(joint, PB_J_TICK)); }
fn pu_indices() { let rows = ui_items(); let i = 0; while i < 4 { let p = m_take(8); store64(p, i); ui_item_add(rows, p); i = i + 1; } return rows; }
fn pu_angle(joint, target) {
    if target { if !pb_j(joint, PB_J_TARGET_ANGLE_VALID) { return "—"; } return m_cat(pu_decimal(pb_degrees(pb_j(joint, PB_J_TARGET_ANGLE))), "°"); }
    if !pb_j(joint, PB_J_ANGLE_VALID) { return "—"; } return m_cat(pu_decimal(pb_degrees(pb_j(joint, PB_J_ANGLE))), "°");
}
fn pu_tcp() {
    let coords = m_take(24); if pb_arm_coords(load64(pu_app), coords, 0) { return "Waiting for joint feedback"; }
    return m_cat(m_cat(m_cat(m_cat(m_cat(pu_decimal(load64(coords)), " / "), pu_decimal(load64(coords + 8))), " / "), pu_decimal(load64(coords + 16))), " mm");
}
view pu_hold_button(key, label, id) {
    button(key, id: key, class: "jog", type: "button", data-hold: m_int(id), disabled: pu_attr(!pu_ready()), text: label);
}
view pu_input(key, label, name, value) {
    div(m_cat(key, "-field"), class: "field") {
        label(m_cat(key, "-label"), for: key, text: label);
        input(key, id: key, name: name, type: "number", step: "any", value: value, required: "");
    }
}
view pu_joint_row(row) {
    let index = load64(row); let key = m_cat("joint-", m_int(index)); let joint = pb_joint(load64(pu_app), index); let locked = pb_vget(pu_app, 37);
    article(key, class: "joint", id: key) {
        div(m_cat(key, "-heading"), class: "joint-heading") {
            h3(m_cat(key, "-name"), text: pr_joint_name(index, 0));
            span(m_cat(key, "-servo"), class: "muted", text: m_cat("Servo ", m_int(pb_j(joint, PB_J_ID))));
            strong(m_cat(key, "-angle"), id: m_cat(key, "-angle"), text: pu_angle(joint, 0));
        }
        p(m_cat(key, "-telemetry"), class: "muted", text: m_cat(m_cat(m_cat(m_cat("Tick ", pu_tick(joint)), " · target "), pu_angle(joint, 1)), m_cat(" · speed ", pu_number(pb_j(joint, PB_J_SPEED)))));
        div(m_cat(key, "-buttons"), class: "joint-buttons") {
            use pu_hold_button(m_cat(key, "-minus"), "−", 10 + index * 2);
            button(m_cat(key, "-stop"), text: "Stop", action: "stop");
            use pu_hold_button(m_cat(key, "-plus"), "+", 11 + index * 2);
            button(m_cat(key, "-zero"), text: "Zero", action: "zero", action_id: index + 1, disabled: pu_attr(!pu_ready()));
        }
        p(m_cat(key, "-status"), class: pu_joint_status_class(joint), text: pu_joint_status(joint));
        p(m_cat(key, "-temperature"), id: m_cat(key, "-temperature"), class: "muted temperature", text: pu_temperature(index));
        details(m_cat(key, "-calibration")) {
            summary(m_cat(key, "-summary"), text: "Limits & calibration");
            p(m_cat(key, "-range"), class: "muted", text: m_cat(m_cat(m_cat(m_cat("Ticks ", pu_number(pb_j(joint, PB_J_MIN))), " → "), pu_number(pb_j(joint, PB_J_MAX))), " · wrapping supported"));
            if locked { p(m_cat(key, "-locked"), class: "muted", text: "Edit puppybot.json and restart to change hardware calibration or limits."); }
            else {
                form(m_cat(key, "-limits"), class: "small-form", action: "limits", action_id: index + 1) {
                    use pu_input(m_cat(key, "-min"), "Minimum tick", "minTick", pu_number(pb_j(joint, PB_J_MIN)));
                    use pu_input(m_cat(key, "-max"), "Maximum tick", "maxTick", pu_number(pb_j(joint, PB_J_MAX)));
                    button(m_cat(key, "-limits-submit"), type: "submit", text: "Apply limits");
                }
                form(m_cat(key, "-reference"), class: "small-form", action: "reference", action_id: index + 1) {
                    use pu_input(m_cat(key, "-reference-angle"), "Current angle (deg)", "angleDeg", "0");
                    button(m_cat(key, "-reference-submit"), type: "submit", text: "Set reference");
                }
            }
        }
    }
}
view app_view() {
    let rows = pu_indices(); let robot = load64(pu_app); let ready = pu_ready(); let drive = pb_robot_drive(robot);
    div("dashboard", id: "dashboard", data-ready: m_int(ready)) {
        header("header") {
            div("brand", id: "brand") { b("brand-name", id: "brand-name", text: "● PuppyBot"); span("brand-subtitle", id: "brand-subtitle", class: "muted", text: "Robot control"); }
            div("header-status", class: "header-status") { span("bus-mode", class: "badge", text: pu_mode()); span("connection", id: "connection", class: "connection", data-mono-status: "", text: "Connecting…"); }
            button("stop-all", id: "stop-all", class: "danger", action: "stop", text: "Stop all");
        }
        main("workspace") {
            div("page-title", class: "page-title") { div("page-title-text") { p("eyebrow", class: "eyebrow", text: "Control workspace"); h1("title", text: "PuppyBot dashboard"); } span("uptime", class: "muted", text: m_cat(m_int(pu_now / 1000), " s uptime")); }
            section("status", class: "status-grid", aria-label: "Robot status") {
                article("output-status", class: "metric") { span("output-label", class: "eyebrow", text: "Outputs"); strong("output-value", id: "output-value", text: pu_state()); span("interlock-value", class: "muted", text: pu_interlock()); }
                article("arm-status", class: "metric") { span("arm-label", class: "eyebrow", text: "Arm"); strong("arm-value", text: pr_mode_name(pb_a(robot, PB_A_MODE))); span("tcp-value", class: "muted", text: pu_tcp()); }
                article("drive-status", class: "metric") { span("drive-label", class: "eyebrow", text: "Drive"); strong("drive-value", text: m_cat(m_cat(pu_number(pb_vget(drive, 6)), " / "), pu_number(pb_vget(drive, 7)))); span("steer-value", class: "muted", text: m_cat(m_cat("Steering ", pu_number(pb_vget(drive, 8))), "°")); }
                article("config-status", class: "metric") { span("config-label", class: "eyebrow", text: "Calibration"); strong("config-value", text: pu_config_state()); span("config-path", class: "muted", text: pb_vget(pu_app, 5)); }
            }
            div("admission", class: "admission") {
                p("admission-help", class: "muted", text: pu_admission_help());
                div("admission-buttons", class: "button-row") {
                    button("enable", id: "enable", class: "primary", action: "enable", text: "Enable outputs", disabled: pu_attr(ready));
                    button("disable", id: "disable", action: "disable", text: "Disable outputs");
                }
            }
            div("control-layout", class: "control-layout") {
                aside("drive-panel", class: "panel drive-panel") {
                    h2("drive-heading", text: "Drive control"); p("drive-help", class: "muted", text: "Hold a direction to drive. Release to stop.");
                    div("dpad", class: "dpad") {
                        use pu_hold_button("drive-forward", "↑ Forward", 1); use pu_hold_button("drive-left", "← Left", 3);
                        button("drive-stop", id: "drive-stop", class: "danger", action: "stop", text: "Stop"); use pu_hold_button("drive-right", "Right →", 4); use pu_hold_button("drive-back", "↓ Back", 2);
                    }
                    h2("tcp-heading", text: "TCP jog"); p("tcp-current", class: "muted", text: pu_tcp());
                    form("tcp-frame", action: "frame", class: "small-form") {
                        label("frame-label", for: "frame", text: "Jog frame"); select("frame", id: "frame", name: "frame", action: "frame") {
                            option("frame-base", value: "base", selected: pu_attr(!pb_vget(pu_app, 24)), text: "Arm base");
                            option("frame-tool", value: "tool", selected: pu_attr(pb_vget(pu_app, 24)), text: "Tool");
                        }
                    }
                    div("tcp-buttons", class: "tcp-buttons") {
                        use pu_hold_button("tcp-forward", "Forward", 20); use pu_hold_button("tcp-back", "Back", 21);
                        use pu_hold_button("tcp-left", "Left", 22); use pu_hold_button("tcp-right", "Right", 23);
                        use pu_hold_button("tcp-up", "Up", 24); use pu_hold_button("tcp-down", "Down", 25);
                    }
                    p("lease-help", class: "muted note", text: "Motion stops on release, focus loss, or loss of the button lease.");
                }
                section("arm-panel", class: "panel") {
                    div("arm-toolbar", class: "toolbar") { h2("arm-heading", text: "Arm control"); form("speed-form", id: "speed-form", action: "speed", class: "speed-form") {
                        label("speed-label", for: "speed", text: "Speed"); input("speed", id: "speed", name: "speed", type: "number", min: "0", max: "32767", value: m_int(pb_vget(pu_app, 23)), required: ""); button("speed-submit", type: "submit", text: "Set");
                    } }
                    div("joints", class: "joints") { each row in rows { use pu_joint_row(row); } }
                    div("arm-buttons", class: "arm-buttons button-row") {
                        button("arm-hold", action: "hold", text: "Hold position", disabled: pu_attr(!ready)); button("arm-stop", class: "danger", action: "stop", text: "Stop arm");
                        button("clear-faults", action: "clear-faults", text: "Clear faults"); button("save", action: "save", text: "Save calibration");
                    }
                    details("targets", class: "target-panel") {
                        summary("targets-heading", text: "Joint targets & coordinates");
                        form("angles", id: "angles", action: "angles", class: "target-form") {
                            h3("angles-heading", text: "Joint target (deg)"); use pu_input("yaw", "Yaw", "yawDeg", "90"); use pu_input("shoulder", "Shoulder", "shoulderDeg", "90");
                            use pu_input("elbow", "Elbow", "elbowDeg", "90"); use pu_input("wrist", "Wrist", "wristDeg", "90");
                            button("angles-submit", type: "submit", class: "primary", text: "Move to angles", disabled: pu_attr(!ready)); button("angles-default", action: "default", text: "Default pose", disabled: pu_attr(!ready));
                        }
                        form("coordinates", id: "coordinates", action: "coordinates", class: "target-form") {
                            h3("coordinates-heading", text: "Coordinate target · robot base (mm)"); use pu_input("coord-x", "X", "xMm", "100"); use pu_input("coord-y", "Y", "yMm", "0");
                            use pu_input("coord-z", "Z", "zMm", "100"); use pu_input("coord-phi", "Tool pitch (deg)", "toolPhiDeg", "90");
                            button("coordinates-submit", type: "submit", class: "primary", text: "Move to coordinates", disabled: pu_attr(!ready));
                        }
                    }
                }
            }
            footer("footer") { span("command-label", class: "eyebrow", text: "Last command"); p("last-command", id: "last-command", text: pu_app + 512); p("action-error", class: "error", role: "alert", data-mono-error: "", text: ""); }
        }
    }
}
fn pu_config_state() { if pb_vget(pu_app, 7) { return "Unsaved changes"; } return "Saved"; }
fn pu_admission_help() {
    if pb_vget(pu_app, 8) { return "Fake servo bus · controls exercise the controller without moving hardware."; }
    if pb_vget(pu_app, 40) { return "Connected to the simulator. Enable after feedback appears; pause or reset returns outputs to monitor mode."; }
    return "Hardware starts in monitor mode. Enable requires fresh position and temperature feedback. Calibration changes require a restart.";
}
