#!/usr/bin/env python3
"""
Write text to Yapo memory via the REST API.
Usage: cat file.txt | python3 yapo_mem_write.py [--prefix "tag"]
"""

import sys, json, urllib.request, argparse

YAPO_URL = "http://app1.alt:3388"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', '-p', type=str, default='', help='Context tag for stored text')
    args = parser.parse_args()
    
    text = sys.stdin.read().strip()
    if not text:
        print("Error: no input", file=sys.stderr)
        sys.exit(1)
    
    payload = json.dumps({"text": text, "prefix": args.prefix}).encode('utf-8')
    req = urllib.request.Request(f"{YAPO_URL}/api/mem/write", data=payload,
                                  headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        print(result.get('message', result.get('success', '')))

if __name__ == '__main__':
    main()
