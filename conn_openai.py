#!/usr/bin/env python3
"""
OpenAI‑compatible backend connector (spec13).
Returns the full assistant message object.
"""

import os, json, urllib.request, urllib.error, socket, sys
from datetime import datetime
from log import log_write
from log import redirect_stderr
redirect_stderr("conn_openai") 

#DEBUG_DUMP = os.environ.get('CONN_OPENAI_DEBUG', 'false').lower() == 'true'
DEBUG_DUMP = True

def generate(server_config: dict, model: str, messages: list, options: dict, tools: list = None, image_data: list = None) -> dict:
    """
    Send a prompt to an OpenAI‑compatible API and return the assistant message object.
    """
    base_url = server_config['url'].rstrip('/')
    api_url = f"{base_url}/v1/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }
    if tools:
        payload["tools"] = tools

    # Sampling parameters
    for param in ["temperature", "max_tokens", "top_k", "top_p", "min_p", "repeat_penalty",
                  "repeat_last_n", "presence_penalty", "frequency_penalty", "seed", "stop", "chat_template_kwargs"]:
        if param in options:
            payload[param] = options[param]

    headers = {"Content-Type": "application/json"}
    api_key = server_config.get("api_key")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    if DEBUG_DUMP:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_write(f"openai {ts}: === API Payload ===\n{json.dumps(payload, indent=2)}")

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(api_url, data=data, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            result = json.loads(resp.read().decode('utf-8'))

            if DEBUG_DUMP:
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                log_write(f"openai {ts}: === API Result ===\n{json.dumps(result, indent=2)}")

            # Extract the assistant message from the first choice
            choice = result["choices"][0]
            return choice["message"]   # dict with 'role', 'content', and optionally 'tool_calls'
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise Exception(f"Backend HTTP {e.code}: {body}")
    except Exception as e:
        raise Exception(f"Backend error: {e}")


def server_reachable(server_config: dict, debug: bool = False) -> bool:
    """Check if the backend is reachable (unchanged)."""
    base_url = server_config['url'].rstrip('/')
    health_url = f"{base_url}/v1/models"
    headers = {"Content-Type": "application/json"}
    api_key = server_config.get("api_key")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = urllib.request.Request(health_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            if debug:
                print(f"  /v1/models returned {resp.status}", file=sys.stderr)
            return resp.status == 200
    except Exception as e:
        if debug:
            print(f"  /v1/models failed: {e}", file=sys.stderr)
    host = server_config['url'].split("://")[-1].split(":")[0]
    try:
        port = int(server_config['url'].split(":")[-1])
    except (ValueError, IndexError):
        port = 80
    try:
        with socket.create_connection((host, port), timeout=5):
            if debug:
                print(f"  TCP connect to {host}:{port} succeeded", file=sys.stderr)
            return True
    except Exception as e:
        if debug:
            print(f"  TCP connect failed: {e}", file=sys.stderr)
    return False
