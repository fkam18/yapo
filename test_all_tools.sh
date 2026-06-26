#!/bin/bash
# test_all_tools.sh – verify that each MCP tool can be called successfully
set -e
cd /home/fkam/apps/yapo

echo "=== Testing all MCP tools ==="

# 1. route_prompt (via yapo-mcp)
echo "--- route_prompt ---"
echo '{"tool":"route_prompt","arguments":{"prompt":"Write a Python function"}}' | python3 yapo_mcp.py
echo ""

# 2. mem_write (via yapo-mcp)
echo "--- mem_write ---"
echo '{"tool":"mem_write","arguments":{"text":"test memory item"}}' | python3 yapo_mcp.py
echo ""

# 3. mem_read (via yapo-mcp)
echo "--- mem_read ---"
echo '{"tool":"mem_read","arguments":{"query":"test"}}' | python3 yapo_mcp.py
echo ""

# 4. summarise_text (via yapo-mcp)
echo "--- summarise_text ---"
echo '{"tool":"summarise_text","arguments":{"text":"This is a long text that needs summarising. It contains multiple sentences.","max_points":2}}' | python3 yapo_mcp.py
echo ""

# 5. web_search (via searxng-mcp, requires npx / searxng running)
echo "--- web_search ---"
echo '{"tool":"web_search","arguments":{"query":"Yapo orchestrator"}}' | python3 -c "
import sys,json,subprocess
req=json.load(sys.stdin)
proc=subprocess.run(['npx','-y','mcp-searxng'], input=json.dumps(req), capture_output=True, text=True, timeout=10)
print(proc.stdout or proc.stderr)
" 2>&1 || echo "web_search failed (SearXNG MCP not running?)"
echo ""

# 6. run_command (via shell-mcp)
echo "--- run_command ---"
echo '{"tool":"run_command","arguments":{"command":"echo hello from tool","timeout":5}}' | python3 shell_mcp.py
echo ""

echo "=== All tools tested ==="
