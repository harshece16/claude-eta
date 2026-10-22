"""Self-check on a synthetic transcript: python3 test_eta.py"""
import json, os, shutil, subprocess, sys, tempfile, time
from datetime import datetime, timezone

def rec(t, **kw): return json.dumps({'timestamp': datetime.fromtimestamp(t, timezone.utc).isoformat(), **kw})

def session(t0, durs):
    """One transcript: a prompt, a tool call, a tool result, a final answer, per turn."""
    out = []
    for i, d in enumerate(durs):
        out += [rec(t0, type='user', message={'content': f'fix bug {i}'}),
                rec(t0 + 1, type='assistant', message={'content': [{'type': 'tool_use'}]}),
                rec(t0 + 2, type='user', toolUseResult={}, message={'content': [{'type': 'tool_result'}]}),
                rec(t0 + d, type='assistant', message={'content': [{'type': 'text'}], 'stop_reason': 'end_turn'})]
        t0 += d + 60
    return out

home = tempfile.mkdtemp(); os.makedirs(f'{home}/projects/p')
os.environ['CLAUDE_CONFIG_DIR'] = home
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eta
eta.MODEL = f'{home}/eta-turns.json'

t = list(eta.turns(session(1e9, [30])))
assert len(t) == 1 and t[0][1] - t[0][0] == 30 and t[0][2] == 1 and t[0][4], t
assert eta.pace([]) is None and abs(eta.pace([10, 1000, 100]) - 100) < 1e-6
assert [r[1] for r in eta.turns(['not json', rec(5, type='user', message={'content': '<system-reminder>x'})])] == []

for k in range(30): open(f'{home}/projects/p/s{k}.jsonl', 'w').write('\n'.join(session(1e9 + k * 1e5, [40] * 4)))
rows = eta.train()
assert len(rows) == 120 and rows[0][5] is None and rows[1][5] == 40, rows[:2]
p50, p90 = eta.predict(rows, 'fix|s', 's')
assert p50 == 40 and p90 == 40, (p50, p90)
assert round(eta.predict(rows, 'fix|s', 's', sess=400)[0]) == round(400 ** .7 * 40 ** .3)  # pulled toward session pace

# status line, run the way Claude Code runs it: first render starts a background train instead of blocking
shutil.copy(eta.__file__, home); os.remove(eta.MODEL)
live = f'{home}/projects/p/live.jsonl'; open(live, 'w').write('\n'.join(session(time.time() - 5, [9999])[:2]))
run = lambda: subprocess.run([sys.executable, f'{home}/eta.py'], input=json.dumps({'transcript_path': live}),
                             capture_output=True, text=True).stdout
assert 'learning' in run()
for _ in range(100):
    time.sleep(.1); out = run()
    if 'ETA ~' in out: break
assert 'ETA ~' in out and '1 tools' in out, out
print('ok:', out.strip())
