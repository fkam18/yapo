#!/bin/bash
# test_baseline_api.sh – Yapo REST API integration tests
# Run from any remote laptop that can reach the Yapo container.
# Usage:  YAPO_HOST=192.168.0.180:3388 ./test_baseline_api.sh

set +e
YAPO_HOST="${YAPO_HOST:-localhost:3388}"
BASE="http://${YAPO_HOST}"
TOTAL=0; PASSED=0; FAILED=0

# helpers
pass() { echo "✓ $1"; PASSED=$((PASSED+1)); TOTAL=$((TOTAL+1)); }
fail() { echo "✗ $1"; FAILED=$((FAILED+1)); TOTAL=$((TOTAL+1)); }
skip() { echo "  (skipped – $1)"; TOTAL=$((TOTAL+1)); }

# simple curl wrapper – returns HTTP body
apicall() {
    # usage: apicall METHOD PATH [BODY]
    local method="$1" path="$2" body="$3"
    if [ -n "$body" ]; then
        curl -s -X "$method" "${BASE}${path}" -H "Content-Type: application/json" -d "$body"
    else
        curl -s -X "$method" "${BASE}${path}"
    fi
}

echo "=== Yapo REST API Baseline Tests ==="
echo "Target: $BASE"
echo ""

# ─── 1. Health check ───
echo "--- Health check ---"
HEALTH=$(apicall GET /api/health)
if echo "$HEALTH" | grep -q 'ok'; then
    pass "GET /api/health → ok"
else
    fail "GET /api/health → $HEALTH"
fi

# ─── 2. Config check ───
echo "--- Config check ---"
CFG=$(apicall GET /api/config)
if echo "$CFG" | grep -q '"yapo_root"'; then
    pass "GET /api/config → contains yapo_root"
else
    fail "GET /api/config → no yapo_root"
fi

# ─── 3. Submit a simple job and wait for it ───
echo "--- Submit a job ---"
JOB_PAYLOAD='{"prompt":"Say hello world in Python","mtype":"","name":"api-test-job"}'
SUBMIT=$(apicall POST /api/submit "$JOB_PAYLOAD")
QNO=$(echo "$SUBMIT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('qno',''))" 2>/dev/null)

if [ -n "$QNO" ]; then
    pass "POST /api/submit → job $QNO created"

    # Wait for completion (up to 120 seconds)
    echo "  Waiting for job $QNO to finish..."
    WAIT_RESULT=$(apicall GET "/api/job/${QNO}?wait=true&timeout=600")
    STATE=$(echo "$WAIT_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))" 2>/dev/null)

    if [ "$STATE" = "done" ]; then
        pass "GET /api/job/${QNO}?wait=true → state=done"
        OUTPUT=$(echo "$WAIT_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); o=d.get('output',''); print(o)" 2>/dev/null)
        if [ -n "$OUTPUT" ]; then
            pass "Job $QNO returned output"
        else
            fail "Job $QNO output is empty"
        fi
    elif [ "$STATE" = "error" ]; then
        fail "Job $QNO ended in error"
    else
        fail "Job $QNO did not finish (state=$STATE)"
    fi
else
    fail "POST /api/submit → no qno returned"
fi

# ─── 4. Job tree ───
echo "--- Job tree ---"
TREE=$(apicall GET /api/tree)
if echo "$TREE" | grep -q '"state"'; then
    pass "GET /api/tree → returned job hierarchy"
else
    fail "GET /api/tree → unexpected response"
fi

# ─── 5. Workspace file management ───
echo "--- Workspace file management ---"
WS_TESTDIR="api_baseline_test"
WS_TESTFILE="${WS_TESTDIR}/hello.txt"
WS_CONTENT="Hello from API baseline test"

# Create directory
MKDIR=$(apicall POST /api/ws/mkdir "{\"path\":\"${WS_TESTDIR}\"}")
if echo "$MKDIR" | grep -q '"success"'; then
    pass "POST /api/ws/mkdir → created $WS_TESTDIR"
else
    fail "POST /api/ws/mkdir → $MKDIR"
fi

# Upload file (base64)
B64=$(echo -n "$WS_CONTENT" | base64 -w0)
UPLOAD=$(apicall POST /api/ws/upload "{\"path\":\"${WS_TESTFILE}\",\"content\":\"${B64}\"}")
if echo "$UPLOAD" | grep -q '"success"'; then
    pass "POST /api/ws/upload → uploaded $WS_TESTFILE"
else
    fail "POST /api/ws/upload → $UPLOAD"
fi

# List directory
LIST=$(apicall GET "/api/ws/list?path=${WS_TESTDIR}")
if echo "$LIST" | grep -q "hello.txt"; then
    pass "GET /api/ws/list → found hello.txt"
else
    fail "GET /api/ws/list → $LIST"
fi

# Download file
DOWNLOAD=$(apicall GET "/api/ws/download?path=${WS_TESTFILE}")
if echo "$DOWNLOAD" | grep -q "$WS_CONTENT"; then
    pass "GET /api/ws/download → correct content"
else
    fail "GET /api/ws/download → expected '$WS_CONTENT', got '$DOWNLOAD'"
fi

# Delete file
DELFILE=$(apicall DELETE "/api/ws/delete?path=${WS_TESTFILE}")
if echo "$DELFILE" | grep -q '"success"'; then
    pass "DELETE /api/ws/delete → deleted $WS_TESTFILE"
else
    fail "DELETE /api/ws/delete → $DELFILE"
fi

# Delete directory
DELDIR=$(apicall DELETE "/api/ws/delete?path=${WS_TESTDIR}")
if echo "$DELDIR" | grep -q '"success"'; then
    pass "DELETE /api/ws/delete → deleted $WS_TESTDIR"
else
    fail "DELETE /api/ws/delete → $DELDIR"
fi

# ─── 6. Job download ───
echo "--- Job download ---"
if [ -n "$QNO" ]; then
    TARGZ="/tmp/yapo_test_job_${QNO}.tar.gz"
    curl -s -o "$TARGZ" "${BASE}/api/job/${QNO}/download"
    if [ -f "$TARGZ" ] && [ "$(file -b --mime-type "$TARGZ")" = "application/gzip" ]; then
        pass "GET /api/job/${QNO}/download → tar.gz received"
        rm -f "$TARGZ"
    else
        fail "GET /api/job/${QNO}/download → not a valid tar.gz"
    fi
else
    skip "job download (no job created)"
fi

# ─── 7. Delete the test job ───
echo "--- Delete test job ---"
if [ -n "$QNO" ]; then
    DELJOB=$(apicall DELETE "/api/job/${QNO}")
    if echo "$DELJOB" | grep -q '"success"'; then
        pass "DELETE /api/job/${QNO} → deleted"
    else
        fail "DELETE /api/job/${QNO} → $DELJOB"
    fi
else
    skip "job deletion (no job created)"
fi

# ─── 8. Log retrieval ───
echo "--- Log retrieval ---"
LOGS=$(apicall GET "/api/logs?lines=10")
if [ -n "$LOGS" ]; then
    pass "GET /api/logs → returned log lines"
else
    fail "GET /api/logs → no log lines"
fi

# ─── 9. Reload config ───
echo "--- Reload config ---"
RELOAD=$(apicall POST /api/reload)
if echo "$RELOAD" | grep -q '"success"'; then
    pass "POST /api/reload → success"
else
    fail "POST /api/reload → $RELOAD"
fi

# ─── FINAL ───
echo ""
echo "=============================================="
echo "API Baseline Test Results"
echo "=============================================="
echo "Total tests:  $TOTAL"
echo "Passed:       $PASSED"
echo "Failed:       $FAILED"
echo "=============================================="
echo ""

if [ "$FAILED" -gt 0 ]; then
    echo "Some API tests failed."
    exit 1
else
    echo "All API baseline tests passed."
    exit 0
fi
