#!/usr/bin/env python3
"""ETA for Claude Code turns, from local transcripts. Zero tokens.
  eta.py train   -> scan ~/.claude/projects, write eta-turns.json, print holdout accuracy (-q: skip)
  eta.py         -> status line (reads Claude Code's status JSON on stdin)
"""
import json, os, sys, glob, time, math, subprocess
from datetime import datetime

ROOT = os.path.join(os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR', '~/.claude')), 'projects')
MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'eta-turns.json')
W = .7  # weight on this session's recent pace; best of 0.3/0.5/0.7 on holdout
SKIP = ('<local-command', 'Caveat:', '<task-notification', '[Request interrupted', '<system-reminder')
MAX_TURN = 2 * 3600  # ponytail: turns over 2h treated as noise (left open overnight)

def ts(s): return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()

def prompt_text(d):
    if d.get('type') != 'user' or d.get('isSidechain') or 'toolUseResult' in d: return None
    c = d.get('message', {}).get('content')
    if isinstance(c, list):
        if any(isinstance(x, dict) and x.get('type') == 'tool_result' for x in c): return None
        c = ' '.join(x.get('text', '') for x in c if isinstance(x, dict))
    if not isinstance(c, str) or not c.strip() or c.lstrip().startswith(SKIP): return None
    return c

def bucket(text):
    w = text.split()
    first = w[0].lower().strip('/:,.!?') if w else ''
    size = 's' if len(w) < 12 else 'm' if len(w) < 60 else 'l'
    return f'{first}|{size}', size

def turns(lines):
    """Yield (start, end, tools, text, done) per real prompt."""
    cur = None
    for l in lines:
        try: d = json.loads(l)
        except ValueError: continue
        t = d.get('timestamp')
        if not t: continue
        text = prompt_text(d)
        if text is not None:
            if cur: yield cur
            cur = [ts(t), ts(t), 0, text, False]
        elif cur and not d.get('isSidechain'):
            if d.get('type') == 'assistant':
                cur[1] = ts(t); m = d.get('message', {})
                cur[2] += sum(1 for x in m.get('content') or [] if isinstance(x, dict) and x.get('type') == 'tool_use')
                if m.get('stop_reason') == 'end_turn': cur[4] = True
            elif d.get('subtype') == 'stop_hook_summary':
                cur[1] = ts(t); cur[4] = True
    if cur: yield cur

def pace(durs):
    """Geometric mean of the session's last 3 finished turns, or None."""
    d = durs[-3:]
    return round(math.exp(sum(map(math.log, d)) / len(d)), 1) if d else None

def ok(s, e, done): return done and 1 <= e - s <= MAX_TURN

def train():
    rows = []
    for f in glob.glob(f'{ROOT}/**/*.jsonl', recursive=True):
        if '/subagents/' in f: continue
        prev = []
        with open(f, errors='ignore') as fh:
            for s, e, n, text, done in turns(fh):
                if ok(s, e, done):
                    b, size = bucket(text)
                    rows.append([s, round(e - s, 1), n, b, size, pace(prev)])
                    prev.append(e - s)
    rows.sort()
    with open(MODEL + '.tmp', 'w') as fh: json.dump(rows, fh)
    os.replace(MODEL + '.tmp', MODEL)
    return rows

def q(xs, p):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None

def predict(rows, b, size, elapsed=0, tools=0, sess=None):
    """Median and p90 of remaining seconds, conditioned on having already run `elapsed`,
    with the median pulled toward this session's recent pace (`sess`, seconds per turn)."""
    for pool in ([r for r in rows if r[3] == b], [r for r in rows if r[4] == size], rows):
        live = [r[1] - elapsed for r in pool if r[1] > elapsed and r[2] >= tools]
        if len(live) >= 20: break
    p50, p90 = q(live, .5), q(live, .9)
    if p50 and sess and sess > elapsed:
        p50 = math.exp(W * math.log(sess - elapsed) + (1 - W) * math.log(p50))
    return p50, p90

def fmt(s):
    if s is None: return '?'
    s = int(s); return f'{s}s' if s < 60 else f'{s//60}m{s%60:02d}s' if s < 3600 else f'{s//3600}h{s%3600//60:02d}m'

def evaluate(rows):
    cut = int(len(rows) * .8); hist, test = rows[:cut], rows[cut:]
    print(f'turns: {len(rows)} (train {len(hist)}, test {len(test)})')
    print('checkpoint   within 2x of p50   under p90   median abs err')
    for at in (0, 30, 120):
        hit = cov = 0; errs = []
        t = [r for r in test if r[1] > at]
        for r in t:
            p50, p90 = predict(hist, r[3], r[4], at, sess=r[5])
            rem = r[1] - at
            hit += p50 / 2 <= rem <= p50 * 2; cov += rem <= p90; errs.append(abs(rem - p50))
        print(f'{"t="+str(at)+"s":<12} {hit/len(t):>8.0%}{"":>11}{cov/len(t):>6.0%}{"":>6}{fmt(q(errs,.5)):>8}   (n={len(t)})')

def statusline():
    try: info = json.load(sys.stdin)
    except ValueError: info = {}
    path = info.get('transcript_path') or ''
    if not os.path.exists(MODEL) or time.time() - os.path.getmtime(MODEL) > 86400:
        if not os.path.exists(MODEL): open(MODEL, 'w').write('[]')
        os.utime(MODEL)  # one background retrain per day, not one per render
        subprocess.Popen([sys.executable, os.path.abspath(__file__), 'train', '-q'], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try: rows = json.load(open(MODEL))
    except ValueError: rows = []
    if not rows: print('ETA: learning from your past sessions…'); return
    try:
        with open(path, 'rb') as fh:  # ponytail: tail 4MB only; a turn longer than that loses its start
            cut = os.path.getsize(path) > 4_000_000; fh.seek(max(0, os.path.getsize(path) - 4_000_000))
            ts_ = list(turns(fh.read().decode(errors='ignore').splitlines()[cut:]))  # drop a partial first line
    except OSError: ts_ = []
    if not ts_: print('ETA –'); return
    s, e, n, text, done = ts_[-1]; b, size = bucket(text)
    sess = pace([t[1] - t[0] for t in ts_[:-1] if ok(t[0], t[1], t[4])])
    if done:
        p50, _ = predict(rows, b, size, sess=sess)
        print(f'last turn {fmt(e - s)} · predicted {fmt(p50)}'); return
    el = time.time() - s
    p50, p90 = predict(rows, b, size, el, n, sess)
    over = ' ⚠ slow' if p50 is None or el > 3 * (predict(rows, b, size)[0] or 1e9) else ''
    print(f'ETA ~{fmt(p50)} (p90 {fmt(p90)}) · {fmt(el)} in · {n} tools{over}')

if __name__ == '__main__':
    if sys.argv[1:2] == ['train']:
        t0 = time.time(); rows = train()
        if '-q' not in sys.argv: evaluate(rows); print(f'scan took {time.time()-t0:.0f}s')
    else: statusline()
