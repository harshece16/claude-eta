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
assert len(list(eta.turns(session(1e9, [30])[:2] + [rec(1e9 + 9, type='user', isMeta=True, message={'content': '[Image: x]'})]))) == 1  # image metadata is not a prompt
assert len(list(eta.turns(session(1e9, [30]) + [rec(1e9 + 99, type='user', isMeta=True, message={'content': 'Another session sent'})]))) == 2  # after a finished turn it is

for k in range(30): open(f'{home}/projects/p/s{k}.jsonl', 'w').write('\n'.join(session(1e9 + k * 1e5, [40] * 4)))
def agent(path, t0, dur, done):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path[:-6] + '.meta.json', 'w').write(json.dumps({'agentType': 'Explore'}))
    end = {'stop_reason': 'end_turn'} if done else {}
    open(path, 'w').write('\n'.join([rec(t0, type='user', isSidechain=True, message={'content': 'find x'}),
                                     rec(t0 + dur, type='assistant', isSidechain=True, message={'content': [{'type': 'tool_use'}], **end})]))
for k in range(25): agent(f'{home}/projects/p/s{k}/subagents/agent-{k}.jsonl', 1e9 + k * 1e5, 50, True)
rows = eta.train()
turn_rows = [r for r in rows if r[4] != 'agent']
assert len(turn_rows) == 120 and turn_rows[0][5] is None and turn_rows[1][5] == 40, turn_rows[:2]
assert sum(r[4] == 'agent' and r[3] == 'agent:Explore' and r[1] == 50 for r in rows) == 25
p50, p90 = eta.predict(rows, 'fix|s', 's')
assert p50 == 40 and p90 == 40, (p50, p90)
assert round(eta.predict(rows, 'fix|s', 's', sess=400)[0]) == round(400 ** .7 * 40 ** .3)  # pulled toward session pace

# status line, run the way Claude Code runs it: first render starts a background train instead of blocking
shutil.copy(eta.__file__, home); os.remove(eta.MODEL)
live = f'{home}/projects/p/live.jsonl'; open(live, 'w').write('\n'.join(session(time.time() - 5, [9999])[:2]))
agent(f'{home}/projects/p/live/subagents/agent-run.jsonl', time.time() - 20, 10, False)
run = lambda: subprocess.run([sys.executable, f'{home}/eta.py'], input=json.dumps({'transcript_path': live}),
                             capture_output=True, text=True).stdout
assert 'learning' in run()
for _ in range(100):
    time.sleep(.1); out = run()
    if 'ETA ~' in out: break
assert 'ETA ~' in out and '1 tool' in out and '1 agent ~' in out, out
print('ok:', out.strip())
