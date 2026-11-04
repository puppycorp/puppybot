#!/usr/bin/env python3
"""Stage a narrowly raised PVDATA04 episode limit in copied sources only."""


def transform(source):
    old = 'fn vd_episode_limit(data) {if load64(data)==load64("PVDATA04") {return 1024;}return 256;}'
    new = 'fn vd_episode_limit(data) {if load64(data)==load64("PVDATA04") {return 1030;}return 256;}'
    if source.count(old) != 1:
        raise ValueError('unexpected dataset limit anchor')
    return source.replace(old, new, 1)
