# SPDX-License-Identifier: GPL-2.0-or-later
"""The Python half of tools/bridge_parity.ts: plays each session (a list of the web page's calls) through
web/bridge.py, as the page's worker does, and writes every reply.

    python3 js/tools/bridge_parity.py sessions.json replies.json

bridge.py works under /work, so this needs a POSIX system where /work can be made (WSL on Windows). Timings
(ms, seconds, the log's times and its packing line) are left out: they differ from run to run.
"""
import hashlib
import importlib
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'web'))


class Data:
    """What a Uint8Array from the page is in Pyodide: to_bytes() gives the bytes."""
    def __init__(self, raw):
        self.raw = raw

    def to_bytes(self):
        return self.raw


def normalize(r):
    if isinstance(r, dict):
        r = {k: normalize(v) for k, v in r.items() if k not in ('ms', 'seconds')}
        if isinstance(r.get('log'), list):
            r['log'] = [x[1] for x in r['log'] if not x[1].startswith('packed the main OS')]
        return r
    if isinstance(r, list):
        return [normalize(x) for x in r]
    return r


def main():
    sessions_path, out_path = sys.argv[1:3]
    with open(sessions_path) as fh:
        sessions = json.load(fh)['sessions']
    import bridge
    out = []
    for i, s in enumerate(sessions):
        for d in ('/work/stock', '/work/mods', '/work/core', '/work/out'):
            shutil.rmtree(d, ignore_errors=True)
        if os.path.exists('/work/settings.json'):          # a fresh page: Pyodide's file system starts empty
            os.remove('/work/settings.json')
        bridge = importlib.reload(bridge)
        replies, ticked = [], []
        for step in s['steps']:
            raw = open(step['file'], 'rb').read() if 'file' in step else None
            args = dict(step.get('args', {}))
            if step.get('sha'):
                args['sha256'] = hashlib.sha256(raw).hexdigest()
            args = {k: (ticked if v == '$ticked' else v) for k, v in args.items()}   # the set the last tick gave
            try:
                r = json.loads(bridge.call(step['call'], json.dumps(args), Data(raw) if raw is not None else None))
            except Exception as e:
                r = {'exception': type(e).__name__, 'message': str(e)}
            if step['call'] == 'tick' and isinstance(r, list):
                ticked = r
            replies.append(normalize(r))
        out.append({'label': s['label'], 'replies': replies})
        print('%3d/%d %s' % (i + 1, len(sessions), s['label']), flush=True)
    with open(out_path, 'w') as fh:
        json.dump(out, fh, indent=1)


if __name__ == '__main__':
    main()
