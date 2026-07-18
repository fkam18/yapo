#!/usr/bin/env python3
"""
cleanup_workspace.py – Remove all files and directories from the Yapo workspace.

Uses the /api/ws/list and /api/ws/delete endpoints to recursively wipe the
entire workspace.  Supports a dry‑run flag and an interactive confirmation.

Usage:
    python cleanup_workspace.py [--base-url http://app1.alt:3388] [--yes] [--dry-run]
"""

import argparse
import sys
import requests
from urllib.parse import urljoin

DEFAULT_BASE_URL = "http://app1.alt:3388"


def list_entries(base_url: str, rel_path: str = "") -> list:
    """Return list of entries for a workspace directory.  Each entry is a dict
    with 'name', 'type' ('file' or 'directory'), and 'size' (for files)."""
    url = urljoin(base_url, "/api/ws/list")
    params = {"path": rel_path} if rel_path else {}
    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"List failed for '{rel_path}': {resp.status_code} {resp.text}")
    return resp.json().get("entries", [])


def delete_path(base_url: str, rel_path: str) -> bool:
    """Delete a file or empty directory at the given relative path.
    Returns True on success (HTTP 200), False on error."""
    url = urljoin(base_url, "/api/ws/delete")
    resp = requests.delete(url, params={"path": rel_path})
    return resp.status_code == 200


def delete_all_recursive(base_url: str, rel_path: str = "", dry_run: bool = False) -> None:
    """Recursively delete everything inside `rel_path`, then the directory itself."""
    entries = list_entries(base_url, rel_path)
    for entry in entries:
        name = entry["name"]
        full_path = f"{rel_path}/{name}" if rel_path else name
        if entry["type"] == "directory":
            # Recurse into sub‑directory first
            delete_all_recursive(base_url, full_path, dry_run)
        # Now delete the file or the (now empty) directory
        if not dry_run:
            ok = delete_path(base_url, full_path)
            if ok:
                print(f"Deleted: {full_path}")
            else:
                print(f"Failed to delete: {full_path}", file=sys.stderr)
        else:
            print(f"[DRY RUN] Would delete: {full_path}")

    # Finally, delete the directory itself if it's not the root (root we keep)
    if rel_path:
        if not dry_run:
            ok = delete_path(base_url, rel_path)
            if ok:
                print(f"Deleted directory: {rel_path}")
            else:
                print(f"Failed to delete directory: {rel_path}", file=sys.stderr)
        else:
            print(f"[DRY RUN] Would delete directory: {rel_path}")


def main():
    parser = argparse.ArgumentParser(description="Clean Yapo workspace completely")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help=f"Dashboard base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation prompt")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be deleted, but don't actually delete")
    args = parser.parse_args()

    # Get root listing to check if workspace is already empty
    try:
        root_entries = list_entries(args.base_url, "")
    except Exception as e:
        print(f"Error connecting to workspace: {e}", file=sys.stderr)
        sys.exit(1)

    if not root_entries:
        print("Workspace is already empty.")
        return

    # Print summary of files/dirs to be deleted
    def count_items(path):
        entries = list_entries(args.base_url, path)
        total = len(entries)
        for e in entries:
            if e["type"] == "directory":
                total += count_items(f"{path}/{e['name']}" if path else e["name"])
        return total

    total = count_items("")
    print(f"Found {total} items in workspace root (including subdirectories).")

    if args.dry_run:
        print("Dry‑run mode – nothing will be deleted.")
    elif not args.yes:
        confirm = input("Are you sure you want to delete EVERYTHING in the workspace? [y/N] ")
        if confirm.strip().lower() != "y":
            print("Aborted.")
            return

    delete_all_recursive(args.base_url, "", dry_run=args.dry_run)
    if not args.dry_run:
        print("Workspace cleaned.")


if __name__ == "__main__":
    main()
