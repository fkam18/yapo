#!/usr/bin/env python3
"""
list_workspace_tree.py – Display the complete workspace as a tree.

Usage:
    python list_workspace_tree.py [--base-url http://app1.alt:3388]
"""

import argparse
import requests
from urllib.parse import urljoin

DEFAULT_BASE_URL = "http://app1.alt:3388"


def list_entries(base_url: str, rel_path: str = "") -> list:
    """Call /api/ws/list and return the 'entries' list."""
    url = urljoin(base_url, "/api/ws/list")
    params = {"path": rel_path} if rel_path else {}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    return data.get("entries", [])


def tree_generator(base_url: str, rel_path: str = "", prefix: str = ""):
    """
    Recursively yield lines of the tree for the directory at `rel_path`.
    The `prefix` string is used to draw the tree structure.
    """
    entries = list_entries(base_url, rel_path)
    count = len(entries)
    for idx, entry in enumerate(entries):
        name = entry["name"]
        is_last = (idx == count - 1)
        connector = "└── " if is_last else "├── "
        yield f"{prefix}{connector}{name}"

        if entry["type"] == "directory":
            # Compute new prefix for children
            extension = "    " if is_last else "│   "
            new_prefix = prefix + extension
            child_path = f"{rel_path}/{name}" if rel_path else name
            yield from tree_generator(base_url, child_path, new_prefix)


def main():
    parser = argparse.ArgumentParser(description="Display workspace directory tree")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help=f"Dashboard base URL (default: {DEFAULT_BASE_URL})")
    args = parser.parse_args()

    print(".")  # root indicator
    try:
        for line in tree_generator(args.base_url):
            print(line)
    except requests.HTTPError as e:
        print(f"API error: {e}", file=sys.stderr)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
