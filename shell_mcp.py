#!/usr/bin/env python3
"""
Yapo Shell MCP server – executes whitelisted commands within the workspace.
Expects a JSON object on stdin: {"tool": "run_command", "arguments": {"command": "...", "timeout": 30}}
Returns the command output on stdout.
"""

import sys, json, subprocess, os, re

# ============================================================
# Configuration – adjust as needed
# ============================================================
WORKSPACE = os.environ.get('YAPO_WORKSPACE', '/ws')
ALLOWED_COMMANDS = {
    'git', 'find', 'grep', 'ls', 'cat', 'head', 'tail', 'wc',
    'diff', 'patch', 'mkdir', 'rm', 'cp', 'mv', 'chmod', 'chown',
    'python3', 'python', 'pip', 'node', 'npm', 'npx',
    'echo' 
}
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120

def validate_command(cmd_str):
    """Basic security: only allow whitelisted commands, no shell chaining."""
    # Extract the first word (the command)
    parts = cmd_str.strip().split()
    if not parts:
        raise ValueError("Empty command")
    base_cmd = os.path.basename(parts[0])  # handle /usr/bin/git -> git
    if base_cmd not in ALLOWED_COMMANDS:
        raise ValueError(f"Command '{base_cmd}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}")

    # Block dangerous shell metacharacters
    dangerous = [';', '&&', '||', '`', '$', '|', '>', '<', '&']
    for char in dangerous:
        if char in cmd_str:
            raise ValueError(f"Character '{char}' not allowed in command")
    return True

def execute_command(cmd_str, timeout):
    """Execute a command safely, returning stdout/stderr."""
    # Run in a shell but with restricted characters already validated.
    # Use subprocess with shell=False and shlex.split for safety, but that would require
    # parsing arguments. For simplicity and because we already filter metacharacters,
    # we use shell=True with the whitelist.
    try:
        result = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=WORKSPACE,
            env={**os.environ, 'HOME': WORKSPACE, 'PWD': WORKSPACE}
        )
        output = result.stdout
        if result.stderr:
            output += '\n' + result.stderr
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as e:
        return f"Error executing command: {str(e)}"

def main():
    # Read JSON from stdin
    raw = sys.stdin.read()
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        sys.exit(1)

    tool = request.get('tool')
    if tool != 'run_command':
        print(f"Unknown tool: {tool}")
        sys.exit(1)

    arguments = request.get('arguments', {})
    cmd = arguments.get('command', '')
    timeout = arguments.get('timeout', DEFAULT_TIMEOUT)
    try:
        timeout = int(timeout)
    except (ValueError, TypeError):
        timeout = DEFAULT_TIMEOUT
    timeout = min(timeout, MAX_TIMEOUT)

    if not cmd:
        print("Error: no command provided")
        sys.exit(1)

    # Validate
    try:
        validate_command(cmd)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Execute
    output = execute_command(cmd, timeout)
    print(output)

if __name__ == '__main__':
    main()
