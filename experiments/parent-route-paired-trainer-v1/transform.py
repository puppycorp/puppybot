#!/usr/bin/env python3
"""Patch only a private, previously verified five-prefix trainer copy."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unexpected previous-trainer source anchor')
    return source.replace(old, new, 1)


def dataset(source):
    old = 'fn vd_episode_limit(data) {if load64(data)==load64("PVDATA04") {return 1030;}return 256;}'
    new = 'fn vd_episode_limit(data) {if load64(data)==load64("PVDATA04") {return 1031;}return 256;}'
    return once(source, old, new)


def train(source):
    source = once(source,
        'episodes==1029 && training_count==933 && pt_length==300',
        'episodes==1031 && training_count==935 && pt_length==300')
    source = once(source,
        'let pt_outbound_skip_aux=active && episode>=928 && episode<933 && !pb_u32(values+40);',
        'let pt_outbound_skip_aux=active && episode>=928 && episode<935 && !pb_u32(values+40);')
    anchor = '// The mapped demonstrations never change, so every row is checked once before training.\nfn pt_check_rows(episodes) {'
    helper = '''// Private paired-data guard: only the seven policy actions are supported.
fn pt_pair_joint7(action) {
    let steer=pb_u32(action);let speed=pb_u32(action+4);
    if !speed {return !steer;}
    return (speed==0x3f800000 || speed==0xbf800000) && (!steer || steer==0x3f19999a || steer==0xbf19999a);
}
// The mapped demonstrations never change, so every row is checked once before training.
fn pt_check_rows(episodes) {'''
    source = once(source, anchor, helper)
    anchor = '            if pt_row_bytes==56 {vp_require(f64_le(f64_magnitude(pb_read_float(values+48)),PB_ONE) && f64_le(f64_magnitude(pb_read_float(values+52)),PB_ONE),"executed demonstration action exceeds [-1,1]");}'
    extra = '''
            // Five original teacher prefixes plus two parent-driven fitting
            // histories have fixed first-event/delivery cutoffs. Their valid
            // suffix frames remain recurrent context, never action/aux labels.
            if episode>=928 && episode<935 {
                let cutoff=162;if episode==929 {cutoff=107;}if episode==930 {cutoff=171;}if episode==931 {cutoff=43;}if episode==932 {cutoff=38;}if episode==933 {cutoff=163;}if episode==934 {cutoff=189;}
                vp_require(frame==0x3f800000 && !pb_u32(values+36) && pb_u32(values+40)==0x3f800000*(t<cutoff),"paired fitting validity or prefix mask differs");
                vp_require(pt_pair_joint7(values+28) && pt_pair_joint7(values+48),"paired fitting action is outside joint-seven codec");
                if episode<933 {vp_require(load64(values+28)==load64(values+48),"original teacher labels or executed actions differ");}
                if episode>=933 && t>=cutoff {vp_require(!load64(values+28),"paired fitting suffix action label must be zero");}
            }'''
    source = once(source, anchor, anchor + extra)
    # Validate every row before initializing HIP or allocating the GPU graph.
    source = once(source, '    // Longer unrolled GRU episodes need more nodes than detector inference.',
                  '    pt_check_rows(episodes);\n    // Longer unrolled GRU episodes need more nodes than detector inference.')
    source = once(source, 'let parameters=pt_prepare(load64(argv+24));pt_batch_open();pt_check_rows(episodes);',
                  'let parameters=pt_prepare(load64(argv+24));pt_batch_open();')
    return source


def workflow(source, old_trainer, new_trainer):
    for value in (str(old_trainer), str(new_trainer)):
        if any(char in value for char in '"\\\n\r'):
            raise ValueError('unsafe private trainer path')
    return once(source, f'vc_add(args,"{old_trainer}");', f'vc_add(args,"{new_trainer}");')
