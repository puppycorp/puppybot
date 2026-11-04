#!/usr/bin/env python3
"""Opt-in small-component experiment, to be applied to a copied source tree."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('source differs from expected anchor')
    return source.replace(old, new, 1)


def transform(dock, main):
    dock = once(dock, 'global ps_dock_count = 0;',
                'global ps_dock_count = 0;\nglobal ps_dock_small_components = 0;')
    dock = once(dock, '    if tail < 4 || tail > 1500 || x1 == 0 || y1 == 0 || x2 == 639 || y2 == 479 || ps_dock_count >= 16 { return 0; }',
                '    let minimum = 4; if ps_dock_small_components { minimum = 3; }\n'
                '    if tail < minimum || tail > 1500 || x1 == 0 || y1 == 0 || x2 == 639 || y2 == 479 || ps_dock_count >= 16 { return 0; }')
    main = once(main, '    ps_dock_diag_dir = pl_environment(argc, argv, "PUPPYBOT_DOCK_DIAG_DIRECTORY");',
                '''    let small_components = pl_environment(argc, argv, "PUPPYBOT_DOCK_SMALL_COMPONENTS");
    if small_components {
        if !pl_equal(small_components, "0") && !pl_equal(small_components, "1") { pl_print(2, "Invalid small component option.\\n"); return 2; }
        ps_dock_small_components = pl_equal(small_components, "1");
    }
    ps_dock_diag_dir = pl_environment(argc, argv, "PUPPYBOT_DOCK_DIAG_DIRECTORY");''')
    return dock, main
