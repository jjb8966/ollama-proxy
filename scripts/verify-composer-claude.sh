#!/usr/bin/env bash
# Verify cursor:composer-2.5 matches gpt-5.5-style tool streaming for Claude Code.
set -euo pipefail

TOKEN="${PROXY_API_TOKEN:-${MY_TOKEN:-cm50cm50cm4xMjMh}}"
BASE="${ANTHROPIC_BASE_URL:-http://127.0.0.1:5002}/v1/messages"
PROMPT="${1:-gpt5.5 opus4.7 composer 2.5 benchmark pricing - use WebSearch}"

python3 - "$TOKEN" "$BASE" "$PROMPT" <<'PY'
import json, sys, urllib.request

token, base, prompt = sys.argv[1:4]
tools = [{
    "name": "WebSearch",
    "description": "search",
    "input_schema": {
        "type": "object",
        "properties": {"search_term": {"type": "string"}},
        "required": ["search_term"],
    },
}]
body = {
    "model": "cursor:composer-2.5",
    "max_tokens": 512,
    "stream": True,
    "messages": [{"role": "user", "content": prompt}],
    "tools": tools,
}
req = urllib.request.Request(
    base,
    data=json.dumps(body).encode(),
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    },
    method="POST",
)
events, text, tool_args, json_deltas = [], "", {}, 0
with urllib.request.urlopen(req, timeout=180) as resp:
    for raw in resp:
        line = raw.decode(errors="replace").strip()
        if not line.startswith("data:"):
            continue
        p = line[5:].strip()
        if p == "[DONE]":
            break
        ev = json.loads(p)
        t = ev.get("type")
        idx = ev.get("index")
        if t == "content_block_start":
            cb = ev.get("content_block", {})
            events.append((idx, "start", cb.get("type"), cb.get("name", "")))
        elif t == "content_block_delta":
            d = ev.get("delta", {})
            if d.get("type") == "text_delta":
                text += d.get("text", "")
            elif d.get("type") == "input_json_delta":
                json_deltas += 1
                tool_args[idx] = tool_args.get(idx, "") + d.get("partial_json", "")
        elif t == "content_block_stop":
            events.append((idx, "stop", "", ""))
        elif t == "message_delta":
            stop = ev.get("delta", {}).get("stop_reason")

ok_args = False
args = ""
for idx in sorted(tool_args):
    candidate = tool_args[idx]
    try:
        json.loads(candidate)
        if candidate.strip():
            args = candidate
            ok_args = True
            break
    except json.JSONDecodeError:
        continue

tool_idx = next((i for i, kind, ty, _ in events if kind == "start" and ty == "tool_use"), None)
text_idx = next((i for i, kind, ty, _ in events if kind == "start" and ty == "text"), None)
failures = []
if not ok_args:
    failures.append("missing or invalid tool JSON args")
if tool_idx is None:
    failures.append("no tool_use block")
# gpt-5.5 / composer: tool_use block first for Claude Code tool UI
if tool_idx is not None and text_idx is not None and not (tool_idx < text_idx):
    failures.append(f"tool block (index {tool_idx}) should precede text (index {text_idx})")
if json_deltas < 10:
    failures.append(f"too few input_json_delta events ({json_deltas})")

print("events:", events[:12])
print("json_deltas:", json_deltas)
print("text_len:", len(text))
print("args:", args[:160])
print("stop_reason:", stop)
if failures:
    print("FAIL:", "; ".join(failures))
    sys.exit(1)
print("PASS: composer stream OK for Claude Code")
PY
