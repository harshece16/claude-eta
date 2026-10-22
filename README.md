# claude-eta

How long will this Claude Code turn take? A status line that predicts it from your own past sessions.
Zero tokens, no network, no dependencies, one Python file.

```
ETA ~3m06s (p90 26m37s) · 59s in · 4 tools
last turn 2m10s · predicted 1m45s
```

While a turn runs you see the likely time left, a "done within" bound, the time so far and the tool
calls so far. When the turn ends you see the actual time next to the prediction, so you can judge it
yourself.

## Install

```sh
mkdir -p ~/.claude/eta
curl -fsSL https://raw.githubusercontent.com/harshece16/claude-eta/main/eta.py -o ~/.claude/eta/eta.py
```

Then add this to `~/.claude/settings.json`:

```json
"statusLine": { "type": "command", "command": "python3 ~/.claude/eta/eta.py", "refreshInterval": 5 }
```

`refreshInterval` makes the line tick during long tool calls; older Claude Code versions ignore it and
update on each message. The first render shows `ETA: learning from your past sessions…` while it scans
`~/.claude/projects` in the background (about 30 s for 3,500 turns). It rescans once a day.

Already have a status line? eta.py reads the same JSON on stdin, so chain it:

```sh
#!/bin/sh
input=$(cat)
echo "$(echo "$input" | your-statusline) · $(echo "$input" | python3 ~/.claude/eta/eta.py)"
```

## How it works

Your transcripts already record when every prompt was sent, every tool call and when the turn ended.
eta.py turns that into a table of past turns, then:

- **At the prompt:** takes the median and 90th percentile of past turns that began with the same first
  word (`fix`, `commit`, `/review`, …) and were of similar length. With fewer than 20 matches it falls
  back to length alone, then to all turns.
- **While the turn runs:** uses only past turns that already lasted this long and made at least this
  many tool calls, and reports their remaining time.
- **This session's pace:** pulls the median toward the geometric mean of the session's last 3 turns.
- **⚠ slow** appears once a turn has run 3x its usual time.

## Accuracy

Check it on your own history:

```sh
python3 ~/.claude/eta/eta.py train
```

This trains on your oldest 80% of turns and tests on the newest 20%. The author's 3,489 turns:

| Point in the turn | Median within 2x of actual | Actual under p90 | Typical error |
|---|---|---|---|
| Prompt sent | 42% | 90% | 2m08s |
| 30 s in | 39% | 91% | 3m53s |
| 2 min in | 40% | 92% | 5m13s |

The p90 is the number to trust. "Done within X" holds 9 times in 10, so you know when it is safe to
walk away. The median is weaker: it lands within 2x about 4 times in 10, because turn times are
heavy-tailed. Here a tenth of turns end in under 8 s and a tenth run past 18 min.

Each of these was tested and moved accuracy by 1 point or less, so none is used: project folder, model,
entrypoint (CLI vs SDK) and permission mode. Session pace added 4 points at the prompt.

## Privacy

eta.py reads local files only and makes no network calls. It writes `eta-turns.json` next to itself. For
each turn that file holds the start time, the duration, the tool count, the prompt's first word and a
length bucket. Nothing else from your prompts is stored.

## Limits

- It reads the last 4 MB of a transcript, so a very long turn can lose its start.
- It treats turns over 2 h as noise, such as a session left open overnight.
- It needs Python 3.8+ and has been tested on macOS. It should work on Linux.

## Test

```sh
python3 test_eta.py
```

## License

MIT
