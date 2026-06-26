#!/usr/bin/env python3
"""
One‑shot GPU suspend test – loads config.toml and executes the suspend_command
for the server named "gpu".
"""
import subprocess, sys

def main():
    # Load config (no extra dependencies, just the TOML parser)
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    try:
        with open('config.toml', 'rb') as f:
            config = tomllib.load(f)
    except FileNotFoundError:
        print("config.toml not found in current directory", file=sys.stderr)
        sys.exit(1)

    # Find the GPU server
    servers = config.get('servers', [])
    gpu = None
    for srv in servers:
        if srv.get('name') == 'gpu':
            gpu = srv
            break

    if not gpu:
        print("Server 'gpu' not found in config.toml", file=sys.stderr)
        sys.exit(1)

    cmd = gpu.get('suspend_command')
    if not cmd:
        print("No suspend_command configured for server 'gpu'.", file=sys.stderr)
        sys.exit(1)

    print(f"Executing: {cmd}")
    try:
        subprocess.run(cmd, shell=True, check=True)
        print("GPU suspend command executed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}", file=sys.stderr)
        sys.exit(e.returncode)

if __name__ == '__main__':
    main()
