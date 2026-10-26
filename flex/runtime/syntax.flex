// Scope the upstream Monolith view compiler to the dashboard declarations.
// Skipping controller/codec lexing keeps extensions within the compiler VM budget.
import "ui/internal/syntax.flex";
fn transform_syntax(context, version) {
    ext_context = context; let i = 0;
    while i < ext_module_count() {
        let path = ext_module_path(i); let n = ext_len(path); let suffix = "/runtime/views.flex"; let size = ext_len(suffix);
        if n < size || !ext_equal(path + n - size, suffix) { store64(ext_module(i) + 32, ext_module_size(i)); }
        i = i + 1;
    }
    return sx_transform(context, version, 0);
}
