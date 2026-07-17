#!/usr/bin/env python3
"""filesystem_mcp.py – simple MCP server for workspace file operations."""
import json, os, sys

WORKSPACE = "/ws"

def safe_path(rel):
    abs_path = os.path.realpath(os.path.join(WORKSPACE, rel))
    # Allow workspace root and any subdirectory
    if abs_path != WORKSPACE and not abs_path.startswith(WORKSPACE + os.sep):
        raise ValueError(f"Path {rel} escapes workspace")
    return abs_path

def handle_request(req):
    tool = req.get("tool")
    args = req.get("arguments", {})

    if tool == "read_file":
        path = safe_path(args["path"])
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return content                          # plain text content

    elif tool == "write_file":
        path = safe_path(args["path"])
        content = args["content"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return "File written successfully."

    elif tool == "list_directory":
        path = safe_path(args.get("path", ""))
        if not os.path.isdir(path):
            return f"Error: not a directory: {args.get('path','')}"
        lines = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                lines.append(f"📁 {name}/")
            else:
                size = os.path.getsize(full)
                lines.append(f"📄 {name} ({size} bytes)")
        return "\n".join(lines) if lines else "(empty directory)"

    elif tool == "create_directory":
        path = safe_path(args["path"])
        os.makedirs(path, exist_ok=True)
        return f"Directory '{args['path']}' created."

    elif tool == "search_files":
        import re
        pattern = re.compile(args["pattern"])
        dir_path = safe_path(args.get("path", ""))
        results = []
        for root, _, files in os.walk(dir_path):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        for lineno, line in enumerate(f, 1):
                            if pattern.search(line):
                                rel = os.path.relpath(fpath, WORKSPACE)
                                results.append(f"{rel}:{lineno}: {line.strip()}")
                except (UnicodeDecodeError, OSError):
                    pass
        return "\n".join(results) if results else "No matches found."

    else:
        return f"Error: unknown tool '{tool}'"

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_request(req)
        except Exception as e:
            resp = {"error": str(e)}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
