#!/usr/bin/env python3
"""Stage per-episode auxiliary masking in a copied native trainer."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unexpected trainer source anchor')
    return source.replace(old, new, 1)


def transform(source, start, end, expected_total=1029, expected_length=300):
    if (any(type(n) is not int for n in (start, end, expected_total, expected_length)) or
            not 0 <= start < end < expected_total <= 1030 or not 1 <= expected_length <= 512):
        raise ValueError('invalid half-open outbound fitting episode range')
    anchor = 'vp_require(pt_data_size==32+episodes*pt_record_size,"truncated demonstration data");'
    source = once(source, anchor, anchor +
        f'vp_require(load64(pt_data)==load64("PVDATA04") && episodes=={expected_total} && '
        f'training_count=={end} && pt_length=={expected_length},"outbound auxiliary range does not match dataset split");')
    anchor = ('        while t<pt_length {let index=t*pt_batch+b;let values=base+pt_length*pt_image_bytes+t*pt_row_bytes;\n'
              '            let frame=vd_valid_word(values,pt_row_bytes);')
    source = once(source, anchor,
        anchor + f'\n            let pt_outbound_skip_aux=active && episode>={start} && episode<{end} && !pb_u32(values+40);')
    source = once(source,
        'if pt_map_aux {let row=pt_batch_map+index*144;if active && frame {',
        'if pt_map_aux {let row=pt_batch_map+index*144;if active && frame && !pt_outbound_skip_aux {')
    source = once(source,
        'if !active {pb_put32(target+16,0);}}',
        'if !active || pt_outbound_skip_aux {pb_put32(target+16,0);}}')
    source = once(source,
        'if !active {pb_put32(target+8,0);}}',
        'if !active || pt_outbound_skip_aux {pb_put32(target+8,0);}}')
    source = once(source,
        '            pb_put32(pt_batch_phase_masks+index*4,pt_phase_mask(pb_u32(values+40),frame,active,pt_phase_from_valid));',
        '            pb_put32(pt_batch_phase_masks+index*4,pt_phase_mask(pb_u32(values+40),frame,active,pt_phase_from_valid));\n'
        '            if pt_outbound_skip_aux {pb_put32(pt_batch_phase_masks+index*4,0);}')
    return source
