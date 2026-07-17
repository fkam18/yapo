#!/usr/bin/env python3
"""
download_ws.py – Pull the entire Yapo workspace to a local folder.

Usage:
    python download_ws.py --folder /local/path [--base-url http://app1.alt:3388]
    YAPO_URL=http://app1.alt:3388 python sync_ws.py --folder /local/path
"""

import argparse
import os
import sys
import requests
from urllib.parse import urljoin

DEFAULT_BASE_URL = "http://app1.alt:3388"

def list_dir(base_url, path=""):
    """List workspace directory contents. Returns list of entries."""
    url = urljoin(base_url, "/api/ws/list")
    params = {"path": path} if path else {}
    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        raise Exception(f"Failed to list '{path}': {resp.status_code} {resp.text}")
    data = resp.json()
    return data.get("entries", [])

def download_file(base_url, remote_path, local_path):
    """Download a single file to the given local path."""
    url = urljoin(base_url, "/api/ws/download")
    params = {"path": remote_path}
    resp = requests.get(url, params=params, stream=True)
    if resp.status_code != 200:
        raise Exception(f"Failed to download '{remote_path}': {resp.status_code}")
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

def sync_workspace(base_url, local_root, remote_path=""):
    """Recursively sync the remote_path (relative to workspace root) into local_root."""
    try:
        entries = list_dir(base_url, remote_path)
    except Exception as e:
        print(f"ERROR listing '{remote_path}': {e}", file=sys.stderr)
        return False

    for entry in entries:
        name = entry["name"]
        remote_full = os.path.join(remote_path, name) if remote_path else name
        local_full = os.path.join(local_root, remote_full)

        if entry["type"] == "directory":
            print(f"DIR  {remote_full}")
            os.makedirs(local_full, exist_ok=True)
            if not sync_workspace(base_url, local_root, remote_full):
                return False
        else:
            print(f"FILE {remote_full}")
            try:
                download_file(base_url, remote_full, local_full)
            except Exception as e:
                print(f"ERROR downloading '{remote_full}': {e}", file=sys.stderr)
                return False
    return True

def main():
    parser = argparse.ArgumentParser(description="Sync Yapo workspace to a local folder")
    parser.add_argument("--folder", required=True, help="Local destination folder")
    parser.add_argument("--base-url", default=os.environ.get("YAPO_URL", DEFAULT_BASE_URL),
                        help=f"Dashboard URL (default: {DEFAULT_BASE_URL})")
    args = parser.parse_args()

    local_folder = os.path.abspath(args.folder)
    os.makedirs(local_folder, exist_ok=True)

    print(f"Syncing workspace from {args.base_url} to {local_folder} ...")
    if sync_workspace(args.base_url, local_folder):
        print("Done.")
    else:
        print("Sync failed.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
