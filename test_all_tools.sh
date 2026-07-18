#!/bin/bash
# SHOULD RUN in docker host as /ws is mounted over there
# test_all_tools.sh – verify that each MCP tool can be called successfully
# Updated to include filesystem tools (spec15) and correct web search test.
set -e
cd /app

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

# 5. web_search (via web_search_mcp.py – custom SearXNG wrapper)
echo "--- web_search ---"
echo '{"tool":"web_search","arguments":{"query":"Yapo orchestrator"}}' | python3 web_search_mcp.py
echo ""

# 6. run_command (via shell-mcp)
echo "--- run_command ---"
echo '{"tool":"run_command","arguments":{"command":"echo hello from tool","timeout":5}}' | python3 shell_mcp.py
echo ""

# 7-11. Filesystem tools (via filesystem_mcp.py, spec15)
# Ensure the workspace directory exists
mkdir -p /ws/testdir

echo "--- list_directory ---"
echo '{"tool":"list_directory","arguments":{"path":"/ws"}}' | python3 filesystem_mcp.py
echo ""

echo "--- create_directory ---"
echo '{"tool":"create_directory","arguments":{"path":"/ws/testdir/sub1"}}' | python3 filesystem_mcp.py
echo ""

echo "--- write_file ---"
echo '{"tool":"write_file","arguments":{"path":"/ws/testdir/hello.txt","content":"Hello from test"}}' | python3 filesystem_mcp.py
echo ""

echo "--- read_file ---"
echo '{"tool":"read_file","arguments":{"path":"/ws/testdir/hello.txt"}}' | python3 filesystem_mcp.py
echo ""

echo "--- search_files ---"
echo '{"tool":"search_files","arguments":{"path":"/ws","pattern":"hello"}}' | python3 filesystem_mcp.py
echo ""

# Clean up
rm -rf /ws/testdir

echo "=== All tools tested ==="
