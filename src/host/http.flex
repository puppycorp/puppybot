import "json.flex";
import "../transport/websocket.flex";

global ph_value_size = 0;
global ph_duplicates = 0;

fn ph_find(data, size, needle, length) {
    let at = 0;
    while at + length <= size { let i = 0; while i < length && load8(data + at + i) == load8(needle + i) { i = i + 1; } if i == length { return at; } at = at + 1; }
    return -1;
}
fn ph_token_char(c) {
    if (c >= 65 && c <= 90) || (c >= 97 && c <= 122) || (c >= 48 && c <= 57) { return 1; }
    let chars = "!#$%&'*+-.^_`|~"; let i = 0; while load8(chars + i) { if c == load8(chars + i) { return 1; } i = i + 1; } return 0;
}
fn ph_headers_valid(data, size) {
    let first = ph_find(data, size, "\r\n", 2); if first < 0 { return 0; }
    let at = first + 2;
    while at < size - 2 {
        let n = ph_find(data + at, size - at, "\r\n", 2); if n <= 0 { return 0; }
        let i = 0; while i < n && ph_token_char(load8(data + at + i)) { i = i + 1; }
        if !i || i >= n || load8(data + at + i) != 58 { return 0; } i = i + 1;
        while i < n { let c = load8(data + at + i); if c < 32 && c != 9 || c == 127 { return 0; } i = i + 1; }
        at = at + n + 2;
    }
    return at == size - 2;
}
fn ph_header(data, size, name) {
    ph_value_size = 0; ph_duplicates = 0;
    let first = ph_find(data, size, "\r\n", 2); if first < 0 { return 0; }
    let at = first + 2; let found = 0;
    while at < size - 2 {
        let n = ph_find(data + at, size - at, "\r\n", 2); if n < 0 { return 0; }
        let colon = ph_find(data + at, n, ":", 1);
        if colon > 0 && pl_case_equal(data + at, colon, name) {
            if found { ph_duplicates = 1; }
            let start = colon + 1; let end = n;
            while start < end && (load8(data + at + start) == 32 || load8(data + at + start) == 9) { start = start + 1; }
            while end > start && (load8(data + at + end - 1) == 32 || load8(data + at + end - 1) == 9) { end = end - 1; }
            found = data + at + start; ph_value_size = end - start;
        }
        at = at + n + 2;
    }
    return found;
}
fn ph_has_token(text, size, token) {
    let at = 0;
    while at < size {
        while at < size && (load8(text + at) == 32 || load8(text + at) == 9 || load8(text + at) == 44) { at = at + 1; }
        let end = at; while end < size && load8(text + end) != 44 { end = end + 1; }
        let trim = end; while trim > at && (load8(text + trim - 1) == 32 || load8(text + trim - 1) == 9) { trim = trim - 1; }
        if pl_case_equal(text + at, trim - at, token) { return 1; } at = end + 1;
    }
    return 0;
}
fn ph_utf8(data, size) {
    let at = 0; while at < size { let n = pj_utf8_size(data + at, size - at); if !n { return 0; } at = at + n; } return 1;
}
fn ph_status(status) {
    if status == 200 { return "200 OK"; } if status == 400 { return "400 Bad Request"; }
    if status == 403 { return "403 Forbidden"; } if status == 415 { return "415 Unsupported Media Type"; }
    if status == 404 { return "404 Not Found"; } if status == 405 { return "405 Method Not Allowed"; }
    if status == 408 { return "408 Request Timeout"; } if status == 409 { return "409 Conflict"; }
    if status == 413 { return "413 Content Too Large"; } if status == 426 { return "426 Upgrade Required"; }
    if status == 431 { return "431 Request Header Fields Too Large"; } if status == 503 { return "503 Service Unavailable"; }
    if status == 501 { return "501 Not Implemented"; } return "500 Internal Server Error";
}
