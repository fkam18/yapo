#!/usr/bin/env python3
"""
Read from Yapo memory via the REST API.
Usage: python3 yapo_mem_read.py -k "search query" [--compact] [-d]
       python3 yapo_mem_read.py -k ""           # read all
       python3 yapo_mem_read.py -k "query" -d   # destructive read
       python3 yapo_mem_read.py -k "" -d        # delete all
"""

import sys, argparse, urllib.request, urllib.parse

YAPO_URL = "http://app1.alt:3388"

def main():
    parser = argparse.ArgumentParser(
        description="Read from Yapo memory via the REST API.",
        epilog="""
Examples:
  yapo_mem_read.py -k "authentication"       # Search by key
  yapo_mem_read.py -k ""                     # Read all documents
  yapo_mem_read.py -k "login" -d             # Destructive read
  yapo_mem_read.py -k "login" --compact      # Compact then read
  yapo_mem_read.py -k "" -d                  # Delete all documents
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('-k', '--key', type=str, default='',
                        help='Search key (empty string = read all documents)')
    parser.add_argument('-d', '--delete', action='store_true', help='Destructive read (delete matching entries)')
    parser.add_argument('--compact', action='store_true', help='Compact database before reading')
    args = parser.parse_args()
    
    params = {
        'key': args.key,
        'del': 'true' if args.delete else 'false',
        'compact': 'true' if args.compact else 'false'
    }
    url = f"{YAPO_URL}/api/mem/read?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url) as resp:
        print(resp.read().decode())

if __name__ == '__main__':
    main()
