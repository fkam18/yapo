#!/usr/bin/env python3
"""
OpenAI‑compatible backend connector.
Works with Ollama, llama.cpp, DeepSeek, Together, Groq, etc.
"""

import json, urllib.request, urllib.error, socket, sys

def generate(server_config: dict, model: str, prompt: str, options: dict) -> str:
    """
    Send a prompt to an OpenAI‑compatible API and return the response text.
    
    Args:
        server_config: dict with keys 'url' and optionally 'api_key'
        model: model name as known by this backend
        prompt: the fully assembled prompt string (Yapo's XML template)
        options: dict with temperature, max_tokens, etc.
    
    Returns:
        The generated text (string).
    
    Raises:
        Exception on any error.
    """
    base_url = server_config['url'].rstrip('/')
    api_url = f"{base_url}/v1/chat/completions"

    # Build the messages array – we send the entire prompt as a single user message
    messages = [
        {"role": "user", "content": prompt}
    ]

    # Build the request payload
    payload = {
        "model": model,
        "messages": messages,
        "temperature": options.get("temperature", 0.0),
        "max_tokens": options.get("num_predict", options.get("max_tokens", 4096)),
        "stream": False
    }

    # Add optional parameters if present
    if "repeat_penalty" in options:
        payload["repeat_penalty"] = options["repeat_penalty"]
    if "repeat_last_n" in options:
        payload["repeat_last_n"] = options["repeat_last_n"]
    if "stop" in options:
        payload["stop"] = options["stop"]

    # Prepare headers
    headers = {
        "Content-Type": "application/json"
    }
    api_key = server_config.get("api_key")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Send the request
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(api_url, data=data, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            # Extract the response text from the OpenAI‑compatible format
            return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise Exception(f"Backend HTTP {e.code}: {body}")
    except Exception as e:
        raise Exception(f"Backend error: {e}")


def server_reachable(server_config: dict, debug: bool = False) -> bool:
    """
    Check if the OpenAI‑compatible backend is responding.
    Uses the /v1/models endpoint first, then falls back to a TCP connect.
    
    Args:
        server_config: dict with keys 'url' and optionally 'api_key'
        debug: if True, prints diagnostic messages to stderr
    
    Returns:
        True if the server is reachable, False otherwise.
    """
    base_url = server_config['url'].rstrip('/')
    health_url = f"{base_url}/v1/models"

    headers = {"Content-Type": "application/json"}
    api_key = server_config.get("api_key")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Try /v1/models first
    try:
        req = urllib.request.Request(health_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            if debug:
                print(f"  /v1/models returned {resp.status}", file=sys.stderr)
            return resp.status == 200
    except Exception as e:
        if debug:
            print(f"  /v1/models failed: {e}", file=sys.stderr)

    # Fallback: TCP connect
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
