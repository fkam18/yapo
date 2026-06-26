#!/usr/bin/env python3
"""
Simple MCP wrapper for web search via SearXNG.
Expects JSON via stdin: {"tool":"web_search","arguments":{"query":"..."}}
Outputs search results as plain text.
"""

import sys, json, urllib.request, urllib.parse, os

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://app2.alt:8080")

def search(query):
    api_url = f"{SEARXNG_URL}/search?q={urllib.parse.quote(query)}&format=json"
    try:
        with urllib.request.urlopen(api_url, timeout=10) as resp:
            data = json.loads(resp.read())
            results = data.get("results", [])
            if not results:
                return "No results found."
            lines = []
            for r in results[:5]:
                title = r.get("title", "")
                url = r.get("url", "")
                snippet = r.get("content", "") or r.get("snippet", "")
                lines.append(f"- {title}: {snippet} ({url})")
            return "\n".join(lines)
    except Exception as e:
        return f"Search error: {e}"

def main():
    req = json.loads(sys.stdin.read())
    query = req.get("arguments", {}).get("query", "")
    if not query:
        print("Error: no query")
        sys.exit(1)
    print(search(query))

if __name__ == "__main__":
    main()
