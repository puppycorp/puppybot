pub(crate) fn base64_encode(input: &[u8], out: &mut [u8]) -> Result<usize, ()> {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let encoded_len = input.len().div_ceil(3) * 4;
    if out.len() < encoded_len {
        return Err(());
    }

    let mut input_pos = 0;
    let mut output_pos = 0;
    while input_pos < input.len() {
        let a = input[input_pos];
        let b = input.get(input_pos + 1).copied().unwrap_or(0);
        let c = input.get(input_pos + 2).copied().unwrap_or(0);
        let remaining = input.len() - input_pos;

        out[output_pos] = TABLE[(a >> 2) as usize];
        out[output_pos + 1] = TABLE[(((a & 0x03) << 4) | (b >> 4)) as usize];
        out[output_pos + 2] = if remaining > 1 {
            TABLE[(((b & 0x0f) << 2) | (c >> 6)) as usize]
        } else {
            b'='
        };
        out[output_pos + 3] = if remaining > 2 {
            TABLE[(c & 0x3f) as usize]
        } else {
            b'='
        };

        input_pos += 3;
        output_pos += 4;
    }

    Ok(encoded_len)
}

pub(crate) fn find_bytes(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

pub(crate) fn trim_ascii(value: &[u8]) -> &[u8] {
    let start = value
        .iter()
        .position(|byte| !byte.is_ascii_whitespace())
        .unwrap_or(value.len());
    let end = value
        .iter()
        .rposition(|byte| !byte.is_ascii_whitespace())
        .map(|idx| idx + 1)
        .unwrap_or(start);
    &value[start..end]
}

pub(crate) fn eq_ignore_ascii_case(left: &[u8], right: &[u8]) -> bool {
    left.len() == right.len()
        && left
            .iter()
            .zip(right.iter())
            .all(|(a, b)| a.eq_ignore_ascii_case(b))
}
