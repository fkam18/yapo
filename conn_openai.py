#!/usr/bin/env python3
"""
OpenAI‑compatible backend connector.
Works with Ollama, llama.cpp, DeepSeek, Together, Groq, etc.
"""

import os, json, urllib.request, urllib.error, socket, sys
from datetime import datetime
from log import log_write

# Set to False to disable debug dumping to /tmp/openai.txt
DEBUG_DUMP = os.environ.get('CONN_OPENAI_DEBUG', 'false').lower() == 'true'

def generate(server_config: dict, model: str, prompt: str, options: dict, image_data: list = None) -> str:
    """
    Send a prompt to an OpenAI‑compatible API and return the response text.
    
    Args:
        image_data: optional list of dicts with 'data' (base64) and 'mime' (e.g. 'image/jpeg')
    """
    base_url = server_config['url'].rstrip('/')
    api_url = f"{base_url}/v1/chat/completions"

    # Build messages – support multimodal if images are present
    if image_data:
        content = [{"type": "text", "text": prompt}]
        for img in image_data:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img['mime']};base64,{img['data']}"}
            })
        messages = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "user", "content": prompt}]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": options.get("temperature", 0.0),
        "max_tokens": options.get("num_predict", options.get("max_tokens", 4096)),
        "stream": False
    }

    if "repeat_penalty" in options:
        payload["repeat_penalty"] = options["repeat_penalty"]
    if "repeat_last_n" in options:
        payload["repeat_last_n"] = options["repeat_last_n"]
    if "stop" in options:
        payload["stop"] = options["stop"]

    headers = {"Content-Type": "application/json"}
    api_key = server_config.get("api_key")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(api_url, data=data, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode('utf-8'))
     
            if DEBUG_DUMP:
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                log_write(f"openai {ts}: === API Call ===\n{json.dumps(result, indent=2)}")
       
            return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise Exception(f"Backend HTTP {e.code}: {body}")
    except Exception as e:
        raise Exception(f"Backend error: {e}")


def server_reachable(server_config: dict, debug: bool = False) -> bool:
    """Check if the OpenAI‑compatible backend is responding."""
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
