#!/usr/bin/env python3
"""
Test the route_prompt MCP tool.
Usage: python3 test_route_model.py "your prompt here"
"""

import sys, json, subprocess

def main():
    if len(sys.argv) < 2:
        print("Usage: test_route_model.py <prompt>", file=sys.stderr)
        sys.exit(1)

    prompt = sys.argv[1]

    # Call the MCP tool exactly as the runner does
    request = json.dumps({"tool": "route_prompt", "arguments": {"prompt": prompt}})

    result = subprocess.run(
        ['python3', 'yapo_mcp.py'],
        input=request,
        capture_output=True,
        text=True,
        timeout=30
    )

    classification = result.stdout.strip()
    print(f"Prompt: {prompt}")
    print(f"Classification: {classification}")

if __name__ == '__main__':
    main()
