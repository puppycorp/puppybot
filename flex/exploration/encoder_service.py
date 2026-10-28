#!/usr/bin/env python3
"""Keep one native GPU encoder resident across an episode's mapping workers."""
import argparse
import json
from pathlib import Path
import signal
import socket

from visual import Encoder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--encoder', required=True, type=Path)
    parser.add_argument('--cache', required=True, type=Path)
    parser.add_argument('--socket', required=True)
    args = parser.parse_args()
    encoder = Encoder(args.encoder, args.cache, use_service=False)
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as server:
            server.bind(args.socket)
            server.listen(1)
            while True:
                client, _ = server.accept()
                with client:
                    request = json.loads(client.recv(8192))
                    assert request['modelSha256'] == encoder.manifest['modelSha256']
                    assert request['weightsSha256'] == encoder.manifest['weightsSha256'] and request['backend'] == encoder.backend
                    frame = dict(rgb=request['rgb'])
                    _, digest = encoder.encode(frame)
                    key = encoder.cache_key(digest)
                    response = dict(modelSha256=encoder.manifest['modelSha256'], weightsSha256=encoder.manifest['weightsSha256'],
                                    backend=encoder.backend, shape=encoder.manifest['outputShape'],
                                    path=str((encoder.cache/(key+'.f32')).resolve()))
                    client.sendall(json.dumps(response).encode())
    except KeyboardInterrupt:
        pass
    finally:
        encoder.close()
        Path(args.socket).unlink(missing_ok=True)


if __name__ == '__main__':
    main()
