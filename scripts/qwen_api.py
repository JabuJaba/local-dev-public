#!/usr/bin/env python
"""
qwen_api.py — Direct Ollama API wrapper for qwen3.6/gemma4 with tool execution.

Replaces Claude Code CLI for local model one-shot sessions. The Claude Code
CLI + Ollama shim combination fails to invoke tools because thinking blocks
in the model response interfere with the CLI's response parser (Sprint 15).
This wrapper calls /api/chat directly (OpenAI format) and implements the
tool-use loop explicitly.

Usage:
  python scripts/qwen_api.py --print "Your prompt here"
  python scripts/qwen_api.py "Your prompt here"
  python scripts/qwen_api.py --model gemma4:26b "Your prompt"
"""

import argparse
import glob as glob_module
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen3.6:35b-a3b-q4_k_m"
MAX_TURNS = 12
MAX_OUTPUT_BYTES = 10_000

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read a file from disk and return its contents with line numbers",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute or relative path to the file"},
                    "offset": {"type": "integer", "description": "Line to start reading from (1-indexed)"},
                    "limit": {"type": "integer", "description": "Max lines to read (default 200)"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Run a shell command and return stdout + stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "Find files matching a glob pattern, returns sorted paths by modification time",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g. **/*.py)"},
                    "path": {"type": "string", "description": "Base directory (default: cwd)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search file contents using a regex pattern",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path": {"type": "string", "description": "File or directory to search (default: cwd)"},
                    "glob": {"type": "string", "description": "Glob filter e.g. *.py"},
                    "-i": {"type": "boolean", "description": "Case-insensitive search"},
                },
                "required": ["pattern"],
            },
        },
    },
]


def _truncate(s: str) -> str:
    if len(s) > MAX_OUTPUT_BYTES:
        return s[:MAX_OUTPUT_BYTES] + f"\n[truncated — {len(s)} bytes total]"
    return s


def tool_read(args: dict) -> str:
    path = args["file_path"]
    offset = max(0, int(args.get("offset", 1)) - 1)
    limit = int(args.get("limit", 200))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        chunk = lines[offset : offset + limit]
        return _truncate("".join(f"{offset + i + 1}\t{l}" for i, l in enumerate(chunk)))
    except Exception as e:
        return f"Error reading {path}: {e}"


def tool_bash(args: dict) -> str:
    cmd = args["command"]
    timeout = int(args.get("timeout", 30))
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        return _truncate(result.stdout + result.stderr)
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


def tool_glob(args: dict) -> str:
    pattern = args["pattern"]
    base = args.get("path", os.getcwd())
    full = os.path.join(base, pattern) if not os.path.isabs(pattern) else pattern
    matches = sorted(glob_module.glob(full, recursive=True), key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
    return "\n".join(matches) if matches else "No files matched"


def tool_grep(args: dict) -> str:
    pattern = args["pattern"]
    path = args.get("path", ".")
    glob_filter = args.get("glob", "")
    ci = args.get("-i", False)

    cmd = ["rg", "--no-heading", "-n"]
    if ci:
        cmd.append("-i")
    if glob_filter:
        cmd += ["--glob", glob_filter]
    cmd += [pattern, path]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return _truncate(r.stdout or "No matches found")
    except FileNotFoundError:
        pass

    cmd2 = ["grep", "-rn"] + (["-i"] if ci else []) + [pattern, path]
    try:
        r = subprocess.run(cmd2, capture_output=True, text=True, timeout=30)
        return _truncate(r.stdout or "No matches found")
    except Exception as e:
        return f"grep error: {e}"


HANDLERS = {
    "Read": tool_read,
    "Bash": tool_bash,
    "Glob": tool_glob,
    "Grep": tool_grep,
}


def call_ollama(model: str, messages: list) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "repeat_penalty": 1.05,
        },
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def run(model: str, prompt: str) -> None:
    messages = [{"role": "user", "content": prompt}]
    total_eval = 0
    total_eval_ns = 0

    for _turn in range(MAX_TURNS):
        resp = call_ollama(model, messages)
        msg = resp.get("message", {})
        content = msg.get("content", "") or ""
        tool_calls = msg.get("tool_calls") or []

        total_eval += resp.get("eval_count", 0)
        total_eval_ns += resp.get("eval_duration", 0)

        if not tool_calls:
            sys.stdout.write(content)
            if content and not content.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()
            break

        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments", {})
            tc_id = tc.get("id", f"call_{name}")

            args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
            handler = HANDLERS.get(name)
            result = handler(args) if handler else f"Unknown tool: {name}"

            messages.append({"role": "tool", "tool_call_id": tc_id, "content": result})

    # tok/s stats to stderr (Phase 6)
    tps = (total_eval / (total_eval_ns / 1e9)) if total_eval_ns > 0 else 0.0
    elapsed = total_eval_ns / 1e9
    label = model.split(":")[0]
    sys.stderr.write(f"\n[{label} | {tps:.1f} tok/s | {total_eval} tokens | {elapsed:.1f}s]\n")
    sys.stderr.flush()


def main() -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--print", dest="prompt_flag", metavar="PROMPT",
                        help="Run prompt non-interactively and print output")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("prompt_pos", nargs="?", metavar="PROMPT",
                        help="Prompt (positional, alternative to --print)")
    args = parser.parse_args()

    prompt = args.prompt_flag or args.prompt_pos
    if not prompt:
        parser.print_help(sys.stderr)
        sys.exit(1)

    try:
        run(args.model, prompt)
    except urllib.error.URLError as e:
        sys.stderr.write(f"Ollama unreachable: {e}\n")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted\n")
        sys.exit(130)


if __name__ == "__main__":
    main()
