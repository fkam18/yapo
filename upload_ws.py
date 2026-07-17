#!/usr/bin/env python3
"""
upload_ws.py – Push a local folder into the Yapo workspace.

Usage:
    python upload_ws.py --folder /local/path [--base-url http://app1.alt:3388]
    YAPO_URL=http://app1.alt:3388 python upload_ws.py --folder /local/path

All files under <folder> will be uploaded to the workspace root.
Sub‑directories are automatically created.
"""

import argparse
import base64
import os
import sys
import requests
from urllib.parse import urljoin

DEFAULT_BASE_URL = "http://app1.alt:3388"

def mkdir_remote(base_url, remote_path):
    """Ensure a remote directory exists."""
    # If remote_path is empty or root, skip
    if not remote_path:
        return
    url = urljoin(base_url, "/api/ws/mkdir")
    resp = requests.post(url, json={"path": remote_path})
    if resp.status_code != 200:
        raise Exception(f"Failed to create directory '{remote_path}': {resp.status_code} {resp.text}")

def upload_file(base_url, local_path, remote_path):
    """Upload a single file (base64 encoded JSON)."""
    url = urljoin(base_url, "/api/ws/upload")
    with open(local_path, 'rb') as f:
        file_bytes = f.read()
    content_b64 = base64.b64encode(file_bytes).decode('utf-8')
    resp = requests.post(url, json={"path": remote_path, "content": content_b64})
    if resp.status_code != 200:
        raise Exception(f"Failed to upload '{remote_path}': {resp.status_code} {resp.text}")

def upload_folder(local_root, base_url, local_dir=""):
    """
    Recursively upload a local directory into the workspace.
    local_dir is the subdirectory relative to local_root.
    """
    current_local_dir = os.path.join(local_root, local_dir) if local_dir else local_root

    try:
        entries = sorted(os.listdir(current_local_dir))
    except OSError as e:
        print(f"ERROR reading '{current_local_dir}': {e}", file=sys.stderr)
        return False

    for name in entries:
        local_path = os.path.join(current_local_dir, name)
        remote_path = os.path.join(local_dir, name) if local_dir else name

        if os.path.isdir(local_path):
            print(f"DIR  {remote_path}")
            # Create remote directory
            try:
                mkdir_remote(base_url, remote_path)
            except Exception as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return False
            # Recurse
            if not upload_folder(local_root, base_url, remote_path):
                return False
        elif os.path.isfile(local_path):
            print(f"FILE {remote_path}")
            try:
                upload_file(base_url, local_path, remote_path)
            except Exception as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return False
        # Ignore symlinks, etc.
    return True

def main():
    parser = argparse.ArgumentParser(description="Upload a local folder to the Yapo workspace")
    parser.add_argument("--folder", required=True, help="Local folder to upload")
    parser.add_argument("--base-url", default=os.environ.get("YAPO_URL", DEFAULT_BASE_URL),
                        help=f"Dashboard URL (default: {DEFAULT_BASE_URL})")
    args = parser.parse_args()

    local_folder = os.path.abspath(args.folder)
    if not os.path.isdir(local_folder):
        print(f"Error: {local_folder} is not a directory", file=sys.stderr)
        sys.exit(1)

    print(f"Uploading from {local_folder} to workspace at {args.base_url} ...")
    if upload_folder(local_folder, args.base_url):
        print("Done.")
    else:
        print("Upload failed.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
