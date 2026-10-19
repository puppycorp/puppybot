// Keep Monolith's unchanged view compiler within the extension VM's budget.
// The Gym's controller/database dependencies contain no declarative views.
import "../../build/flex/gym-monolith-syntax.flex";

fn gym_view_module(path, suffix) {
    let n = ext_len(path); let m = ext_len(suffix); return n >= m && ext_equal(path + n - m, suffix);
}
fn transform_syntax(context, version) {
    ext_context = context; let i = 0;
    while i < ext_module_count() {
        let path = ext_module_path(i);
        if !gym_view_module(path, "/gym/views.flex") && !gym_view_module(path, "/monolith/server.flex") {
            // Retain original module indices and edit ranges. Skip only lexing.
            store64(ext_module(i) + 32, ext_module_size(i));
        }
        i = i + 1;
    }
    return gym_monolith_transform(context, version);
}
