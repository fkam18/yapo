#!/usr/bin/env python3
"""
catanswer.py – Extract the answer from a Yapo job output.
Usage: catjob.py 14 | catanswer.py
       catanswer.py < job_output.txt
"""
import sys, json, re

def extract_json(text: str):
    """Find and parse the JSON object in text. Returns the parsed dict."""
    # Try direct parse of the whole text
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find the first { and its matching }
    start = text.find('{')
    if start == -1:
        raise ValueError("No JSON object found in input")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                snippet = text[start:i+1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    raise ValueError(f"Invalid JSON: {snippet[:120]}...")
    raise ValueError("Unmatched braces in input")

def main():
    if sys.stdin.isatty():
        print("Error: No input. Pipe catjob.py output to this script.", file=sys.stderr)
        print("Usage: catjob.py <qno> | catanswer.py", file=sys.stderr)
        sys.exit(1)

    text = sys.stdin.read()
    if not text.strip():
        print("Error: Empty input", file=sys.stderr)
        sys.exit(1)

    try:
        data = extract_json(text)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    answer = data.get('answer', '')
    if answer:
        print(answer)
    else:
        print("No answer field found in output.", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
