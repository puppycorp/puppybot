#!/usr/bin/env python3
"""Transform a private diverse-scene generator copy; never generate scenes."""


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('unexpected generator source shape')
    return text.replace(old, new, 1)


def transform(source):
    source = once(source, 'global dv_held_out=0;', 'global dv_held_out=0;\nglobal dv_selection=0;')
    source = once(source, 'if dv_held_out {pl_text(b,",\\\"reservedHeldOut\\\":true");}',
                  'if dv_held_out {pl_text(b,",\\\"reservedHeldOut\\\":true");}if dv_selection {pl_text(b,",\\\"selectionOnly\\\":true");}')
    anchor = 'fn main(argc,argv) {'
    function = '''// This role is reserved for selection; it is not a fitting dataset.
fn dv_role_allowed(role,first,end,wide,no_obstacle) {
    let fit=pl_equal(role,"fit");let validation=pl_equal(role,"validation");let development=pl_equal(role,"development");
    let wide_development=pl_equal(role,"wide-development");let held_out=pl_equal(role,"held-out");let selection=pl_equal(role,"selection");
    if first<0 || end<=first {return 0;}
    return (fit && first>=26 && end<=126) || (validation && first>=126 && end<=218 && (end<=180 || first>=188)) ||
        (development && !wide && first>=180 && end<=188) || (wide_development && wide && first>=218 && end<=226) ||
        (held_out && first>=226 && end<=290) || (selection && !wide && !no_obstacle && first>=290 && end<=354);
}
'''
    source = once(source, anchor, function + anchor)
    source = once(source, 'fit|validation|development|wide-development|held-out [--wide-heading]',
                  'fit|validation|development|wide-development|held-out|selection [--wide-heading]')
    old = 'vc_require(fit || validation || development || wide_development || held_out,"invalid dataset role");vc_require((fit && first>=26 && end<=126) || (validation && first>=126 && end<=218 && (end<=180 || first>=188)) || (development && !dv_wide_heading && first>=180 && end<=188) || (wide_development && dv_wide_heading && first>=218 && end<=226) || (held_out && first>=226 && end<=290),"layout IDs must use their disjoint role ranges");'
    source = once(source, old, 'vc_require(dv_role_allowed(role,first,end,dv_wide_heading,dv_no_obstacle),"layout IDs must use their disjoint role ranges");')
    source = once(source, '    dv_held_out=held_out;while layout<end',
                  '    dv_held_out=held_out;dv_selection=pl_equal(role,"selection");while layout<end')
    return source
