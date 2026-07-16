#!/usr/bin/env python3
"""
Yapo MCP server – provides route_prompt, mem_write, mem_read, summarise_text.
Reads server URLs from config.toml (via YAPO_CONFIG).
"""

import sys
import json
import subprocess
import os
import urllib.request
import urllib.error

from config import load_config, get_server

# Load config to get the NUC server URL
_config = load_config()
_nuc_server = get_server('nuc')
NUC_OLLAMA_URL = _nuc_server['url'] if _nuc_server else 'http://192.168.0.180:11434'

SUMMARISE_SCRIPT = os.path.join(os.path.dirname(__file__), 'summarise.py')
MEMORY_SCRIPT = os.path.join(os.path.dirname(__file__), 'memory.py')
ROUTER_MODEL = "qwen2.5:3b"

DEFAULT_TOP_K = 15

def route_prompt(args):
    prompt = args.get('prompt', '')
    import urllib.request, urllib.error
    payload = {
        "model": ROUTER_MODEL,
        "prompt": f"Classify this task as exactly ONE word: code, others, or visual. Do not write anything else.\n\nTask: {prompt}\n\nClassification:",
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 5}
    }
    api_url = f"{NUC_OLLAMA_URL}/api/generate"
    data = json.dumps(payload).encode('utf-8')
    try:
        req = urllib.request.Request(api_url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            response_text = result.get('response', '').strip().lower()
            # Extract the first valid keyword
            for word in response_text.split():
                word = word.strip('.,;:!?"\'-')
                if word in ('code', 'others', 'visual'):
                    return word
            # Fallback: check if any keyword appears anywhere
            if 'code' in response_text:
                return 'code'
            elif 'others' in response_text:
                return 'others'
            elif 'visual' in response_text:
                return 'visual'
            return response_text  # let runner handle it
    except Exception as e:
        print(f"Router error: {e}", file=sys.stderr)
        return ""

def mem_delete(args):
    query = args.get('query', '')
    top_k = int(args.get('top_k', DEFAULT_TOP_K))
    
    cmd = [sys.executable, MEMORY_SCRIPT, 'delete']
    if query:
        cmd.extend(['--query', query, '--top-k', str(top_k)])
    else:
        cmd.append('--read-all')
    
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.stderr.strip()

def mem_compact(args):
    """Run memory.py compact to remove duplicates."""
    p = subprocess.run([sys.executable, MEMORY_SCRIPT, 'compact'], capture_output=True, text=True)
    return p.stderr.strip()

def mem_write(args):
    text = args.get('text', '')
    prefix = args.get('prefix', '')
    
    cmd = [sys.executable, MEMORY_SCRIPT, 'write']
    if prefix:
        cmd.extend(['--prefix', prefix])
    
    p = subprocess.run(cmd, input=text, capture_output=True, text=True)
    return p.stderr.strip()

def mem_read(args):
    query = args.get('query', '')
    top_k = int(args.get('top_k', DEFAULT_TOP_K))
    
    cmd = [sys.executable, MEMORY_SCRIPT, 'read']
    if query:
        cmd.extend(['--query', query, '--top-k', str(top_k)])
    else:
        cmd.append('--read-all')
    
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.stdout.strip()

def summarise_text(args):
    text = args.get('text', '')
    max_points = args.get('max_points', 10)
    p = subprocess.run([sys.executable, SUMMARISE_SCRIPT, '--mode', 'document'],
                       input=text, capture_output=True, text=True)
    lines = p.stdout.strip().split('\n')[:max_points]
    return '\n'.join(lines)

def main():
    input_data = sys.stdin.read()
    print(f"MCP received: {input_data[:200]}", file=sys.stderr)  # ADD THIS
    request = json.loads(input_data)
    tool = request['tool']
    arguments = request.get('arguments', {})

    if tool == 'route_prompt':
        result = route_prompt(arguments)
    elif tool == 'mem_write':
        result = mem_write(arguments)
    elif tool == 'mem_read':
        result = mem_read(arguments)
    elif tool == 'summarise_text':
        result = summarise_text(arguments)
    else:
        result = f"Unknown tool: {tool}"

    print(result)


if __name__ == '__main__':
    main()
