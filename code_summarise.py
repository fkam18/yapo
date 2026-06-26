#!/usr/bin/env python3
"""
Hybrid Code Harvester
Extracts code snippets via AST, then uses the summarise model to translate them
into concise natural language embedding points.
Usage: code_summarise.py --input <file> --output <file>
       code_summarise.py --input <file>
       cat code.py | code_summarise.py
"""

import ast
import sys
import json
import argparse
import urllib.request
from config import load_config, get_model


def clean_summary_text(text: str) -> str:
    text = text.replace('\n', ' ').strip()
    
    prefixes = [
        "the provided python code snippet is designed to",
        "the provided python code snippet is",
        "the provided python code snippet",
        "the provided python script is designed to",
        "the provided python script",
        "the provided code snippet is designed to",
        "the provided code snippet is",
        "the provided code snippet",
        "this code block is designed to",
        "this code block achieves the following",
        "this code block achieves",
        "this function is designed to",
        "this function",
        "this script",
        "is designed to",
        "designed to",
        "is used to",
        "achieves the following",
        "achieves"
    ]
    
    text_lower = text.lower()
    for prefix in prefixes:
        if text_lower.startswith(prefix):
            text = text[len(prefix):].strip()
            text = text.lstrip(" :,-")
            break
            
    if text:
        text = text[0].lower() + text[1:]
        
    return text


def ask_ollama(url: str, model: str, code_snippet: str, options: dict) -> str:
    api_url = f"{url}/api/generate"
    backticks = "```"
    prompt = f"Code snippet:\n{backticks}\n{code_snippet}\n{backticks}\n\nThis code block achieves the following: "

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options
    }

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(api_url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            summary = result.get('response', '').strip()
            return clean_summary_text(summary)
    except Exception as e:
        return f"Error analyzing block: {e}"


def main():
    parser = argparse.ArgumentParser(description="Extract and summarise Python code functions/classes")
    parser.add_argument('--input', '-i', type=str, help='Input Python file (default: stdin)')
    parser.add_argument('--output', '-o', type=str, help='Output file (default: stdout)')
    args = parser.parse_args()

    # Read input
    if args.input:
        with open(args.input) as f:
            source_code = f.read()
    elif not sys.stdin.isatty():
        source_code = sys.stdin.read()
    else:
        print("Error: No input. Use --input <file> or pipe to stdin.", file=sys.stderr)
        sys.exit(1)

    if not source_code.strip():
        print("Error: Empty input.", file=sys.stderr)
        sys.exit(1)

    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        print(f"Syntax Error parsing input code: {e}", file=sys.stderr)
        sys.exit(1)

    # Load model config from config.toml
    model_cfg = get_model('summarise')
    if not model_cfg:
        print("Error: No 'summarise' model defined in config.toml", file=sys.stderr)
        sys.exit(1)

    url = model_cfg.get('url', 'http://localhost:11434')
    model = model_cfg['name']

    # Build options dict from model config
    options = {
        "temperature": model_cfg.get('temperature', 0.0),
        "num_predict": model_cfg.get('max_tokens', 30),
        "stop": ["\n", ".", " -"],
    }
    
    if 'repeat_penalty' in model_cfg:
        options['repeat_penalty'] = model_cfg['repeat_penalty']
    if 'repeat_last_n' in model_cfg:
        options['repeat_last_n'] = model_cfg['repeat_last_n']

    print(f"Processing {args.input or 'stdin'} via {model}...", file=sys.stderr)

    # Collect output
    output_lines = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            raw_snippet = ast.unparse(node)
            summary = ask_ollama(url, model, raw_snippet, options)
            node_type = "Class" if isinstance(node, ast.ClassDef) else "Function"
            output_lines.append(f"- {node_type} {node.name}: {summary}")

    output_text = '\n'.join(output_lines)

    # Write output
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output_text)
        print(f"Wrote {len(output_lines)} snippets to {args.output}", file=sys.stderr)
    else:
        print(output_text)


if __name__ == "__main__":
    main()
