#!/bin/bash
# test_baseline.sh – Yapo baseline integration tests
# Run before publishing a release.

set +e   # Don't exit on first error – we want to run all tests
cd "$(dirname "$0")"

# ---------- CONFIG ----------
YAPO_CONFIG="${YAPO_CONFIG:-config.toml}"
export YAPO_CONFIG
YAPO_ROOT=$(python3 -c "from config import load_config; print(load_config().get('yapo_root','/tmp/yapo_test'))")
TEST_ROOT="/tmp/yapo_baseline_test"
JOBS_DIR="${TEST_ROOT}/jobs"
TOTAL=0
PASSED=0
FAILED=0

# ---------- HELPERS ----------
pass() { echo "✓ $1"; PASSED=$((PASSED+1)); TOTAL=$((TOTAL+1)); }
fail() { echo "✗ $1"; FAILED=$((FAILED+1)); TOTAL=$((TOTAL+1)); }
skip() { echo "  (skipped – $1)"; TOTAL=$((TOTAL+1)); }

cleanup_test() {
    rm -rf "$TEST_ROOT"
}

# ---------- SETUP ----------
cleanup_test
mkdir -p "${JOBS_DIR}/"{ready,processing,pending,done,error}

# Override yapo_root for this test so we don't touch real jobs
cat > /tmp/yapo_test_config.toml << EOF
yapo_root = "${TEST_ROOT}"
$(grep -v '^yapo_root' "$YAPO_CONFIG")
EOF
export YAPO_CONFIG=/tmp/yapo_test_config.toml

echo "=== Yapo Baseline Tests ==="
echo "Test root: ${TEST_ROOT}"
echo ""

# =========================================================
# TEST 1 – Router MCP tool
# =========================================================
echo "--- Router MCP tool ---"
RESULT=$(echo '{"tool":"route_prompt","arguments":{"prompt":"Write a Python function"}}' | python3 yapo_mcp.py 2>/dev/null)
if [[ "$RESULT" == "code" || "$RESULT" == "others" || "$RESULT" == "visual" ]]; then
    pass "route_prompt returned '$RESULT'"
else
    fail "route_prompt returned '$RESULT' (expected code/others/visual)"
fi

# =========================================================
# TEST 2 – Memory write & read
# =========================================================
echo "--- Memory write & read ---"
TEST_TEXT="baseline-test-memory-$(date +%s)"

# Write
WRITE_RESULT=$(echo "{\"tool\":\"mem_write\",\"arguments\":{\"text\":\"$TEST_TEXT\"}}" | python3 yapo_mcp.py 2>/dev/null)
if echo "$WRITE_RESULT" | grep -q "Stored"; then
    pass "mem_write stored a fact"
else
    fail "mem_write failed: $WRITE_RESULT"
fi

# Read – give it a moment to propagate
sleep 2
READ_RESULT=$(echo "{\"tool\":\"mem_read\",\"arguments\":{\"query\":\"$TEST_TEXT\"}}" | python3 yapo_mcp.py 2>/dev/null)
if echo "$READ_RESULT" | grep -q "$TEST_TEXT"; then
    pass "mem_read found the stored fact"
else
    fail "mem_read did not find the stored fact: $READ_RESULT"
fi

# =========================================================
# TEST 3 – Summarise tool
# =========================================================
echo "--- Summarise tool ---"
SUMMARY=$(echo '{"tool":"summarise_text","arguments":{"text":"Yapo is an orchestrator. It manages jobs. It uses MCP tools. It supports GPU energy management.","max_points":2}}' | python3 yapo_mcp.py 2>/dev/null)
if [ -n "$SUMMARY" ]; then
    pass "summarise_text returned output: ${SUMMARY:0:80}..."
else
    fail "summarise_text returned empty output"
fi

# =========================================================
# TEST 4 – Shell tool
# =========================================================
echo "--- Shell tool ---"
LS_RESULT=$(echo '{"tool":"run_command","arguments":{"command":"ls -la"}}' | python3 shell_mcp.py 2>/dev/null)
if echo "$LS_RESULT" | grep -q "total"; then
    pass "run_command executed 'ls -la'"
else
    fail "run_command failed: $LS_RESULT"
fi

# =========================================================
# TEST 5 – Web search tool
# =========================================================
echo "--- Web search tool ---"
SEARCH_RESULT=$(echo '{"tool":"web_search","arguments":{"query":"Yapo orchestrator"}}' | python3 web_search_mcp.py 2>/dev/null)
if [ -n "$SEARCH_RESULT" ]; then
    pass "web_search returned results"
else
    fail "web_search returned empty output (SearXNG may be unreachable)"
fi

# =========================================================
# TEST 6 – Jobber CRUD
# =========================================================
echo "--- Jobber CRUD ---"
QNO=$(python3 jobber.py create --type main --state ready --model "" --prompt-file /dev/stdin <<< "test job" 2>/dev/null)
if [ -n "$QNO" ] && [ -d "${JOBS_DIR}/ready/$QNO" ]; then
    pass "jobber create: job $QNO in ready"
else
    fail "jobber create failed"
fi

python3 jobber.py move "$QNO" processing 2>/dev/null
if [ -d "${JOBS_DIR}/processing/$QNO" ]; then
    pass "jobber move: job $QNO → processing"
else
    fail "jobber move failed"
fi

# Move back to ready for cleanup
python3 jobber.py move "$QNO" ready 2>/dev/null

# =========================================================
# TEST 7 – Full job lifecycle (manual runner)
# =========================================================
echo "--- Full job lifecycle ---"
JOB_QNO=$(python3 jobber.py create --type main --state ready --model "" --prompt-file /dev/stdin <<< "Say hello world in Python" 2>/dev/null)
python3 jobber.py move "$JOB_QNO" processing 2>/dev/null

# Run the runner (this calls the router, then the main LLM)
RUNNER_OUTPUT=$(python3 runner.py "$JOB_QNO" 2>&1) || true
if [ -d "${JOBS_DIR}/done/$JOB_QNO" ]; then
    pass "Job $JOB_QNO completed (done)"
    OUTPUT=$(cat "${JOBS_DIR}/done/$JOB_QNO/output.txt" 2>/dev/null)
    if echo "$OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'done' in d" 2>/dev/null; then
        pass "Job output is valid JSON with 'done'"
    else
        fail "Job output is not valid done JSON"
    fi
elif [ -d "${JOBS_DIR}/pending/$JOB_QNO" ]; then
    pass "Job $JOB_QNO is pending (tool call) – normal for some models"
    # Force‑complete it by moving to done (clean up)
    python3 jobber.py move "$JOB_QNO" done 2>/dev/null || true
elif [ -d "${JOBS_DIR}/error/$JOB_QNO" ]; then
    fail "Job $JOB_QNO ended in error"
    echo "  Runner output:"
    echo "$RUNNER_OUTPUT"
    echo "  Job error details:"
    cat "${JOBS_DIR}/error/$JOB_QNO/output.txt" 2>/dev/null || echo "  (no output.txt)"
    cat "${JOBS_DIR}/error/$JOB_QNO/job.toml" 2>/dev/null
else
    fail "Job $JOB_QNO not found in done/pending/error"
    echo "  Runner output:"
    echo "$RUNNER_OUTPUT"
fi

# =========================================================
# TEST 8 – GPU power management (if configured)
# =========================================================
echo "--- GPU power management ---"

# Check if GPU server is configured with WoL/suspend
GPU_CONFIGURED=$(python3 -c "
from config import load_config
config = load_config()
for s in config.get('servers',[]):
    if s.get('name') == 'gpu' and s.get('schedulable') and s.get('mac_address'):
        print('yes')
        break
" 2>/dev/null)

if [ "$GPU_CONFIGURED" = "yes" ]; then
    # Test health check
    REACHABLE=$(python3 -c "
from config import load_config, get_server
from conn_openai import server_reachable
import sys
srv = get_server('gpu')
print('yes' if srv and server_reachable(srv, debug=True) else 'no')
" 2>&1)
    if echo "$REACHABLE" | tail -1 | grep -q "yes"; then
        pass "GPU health check: reachable"

        # Test suspend (only if suspend_command is configured)
        SUSPEND_CMD=$(python3 -c "
from config import load_config, get_server
srv = get_server('gpu')
print(srv.get('suspend_command',''))
" 2>/dev/null)
        MAC=$(python3 -c "
from config import load_config, get_server
srv = get_server('gpu')
print(srv.get('mac_address',''))
" 2>/dev/null)

        if [ -n "$SUSPEND_CMD" ] && [ -n "$MAC" ]; then
            echo "  Suspending GPU for power test..."
            eval "$SUSPEND_CMD" 2>/dev/null || true

            # Wait for GPU to fully suspend
            SUSPEND_WAIT=60
            echo "  Waiting ${SUSPEND_WAIT} seconds for GPU to fully suspend..."
            sleep "$SUSPEND_WAIT"

            REACHABLE2=$(python3 -c "
from config import load_config, get_server
from conn_openai import server_reachable
import sys
srv = get_server('gpu')
print('yes' if srv and server_reachable(srv, debug=True) else 'no')
" 2>&1)
            if echo "$REACHABLE2" | tail -1 | grep -q "no"; then
                pass "GPU suspended successfully (unreachable)"

                # Wake it up
                echo "  Waking GPU via WoL..."
                python3 -c "
from config import load_config, get_server
from yapo import send_wol
srv = get_server('gpu')
if srv: send_wol(srv['mac_address'])
" 2>/dev/null

                # Wait for GPU to fully boot
                WAKE_WAIT=120
                echo "  Waiting ${WAKE_WAIT} seconds for GPU to fully boot..."
                sleep "$WAKE_WAIT"

                REACHABLE3=$(python3 -c "
from config import load_config, get_server
from conn_openai import server_reachable
import sys
srv = get_server('gpu')
print('yes' if srv and server_reachable(srv, debug=True) else 'no')
" 2>&1)
                if echo "$REACHABLE3" | tail -1 | grep -q "yes"; then
                    pass "GPU woke up successfully (reachable)"
                else
                    fail "GPU did not wake up after WoL"
                fi
            else
                fail "GPU still reachable after suspend command"
            fi
        else
            echo "  (no suspend_command configured – skipping suspend/wake test)"
        fi
    else
        fail "GPU health check: NOT reachable"
        echo "  Health check debug: $REACHABLE"
    fi
else
    echo "  (no GPU server configured with schedulable=true and mac_address – skipping)"
fi

# =========================================================
# TEST 9 – Backend health check via connector
# =========================================================
echo "--- Backend health check ---"
HEALTH=$(python3 -c "
from config import load_config, get_server
from conn_openai import server_reachable
import sys
srv = get_server('nuc')
if srv:
    result = server_reachable(srv, debug=True)
    print('yes' if result else 'no')
else:
    print('no')
" 2>&1)
if echo "$HEALTH" | tail -1 | grep -q "yes"; then
    pass "conn_openai.server_reachable works for NUC"
else
    fail "conn_openai.server_reachable failed for NUC (server running?)"
    echo "  Health check debug: $HEALTH"
fi

# =========================================================
# FINAL SUMMARY
# =========================================================
echo ""
echo "=============================================="
echo "Baseline Test Results"
echo "=============================================="
echo "Total tests:  $TOTAL"
echo "Passed:       $PASSED"
echo "Failed:       $FAILED"
echo "=============================================="
echo ""

# Cleanup
cleanup_test

if [ "$FAILED" -gt 0 ]; then
    echo "Some tests failed."
    exit 1
else
    echo "All baseline tests passed."
    exit 0
fi
