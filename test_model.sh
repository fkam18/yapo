#!/bin/bash
# test_model.sh – test a model on GPU (192.168.0.158) for Yapo JSON compliance
# Usage: bash test_model.sh <model_name>

if [ -z "$1" ]; then
    echo "Usage: $0 <model_name>"
    exit 1
fi

MODEL="$1"
OLLAMA_URL="http://192.168.0.158:11434"

echo "Testing model: $MODEL"

# Build the same prompt the runner uses (simplified)
PROMPT=$(cat <<'EOF'
<GOAL>
Say hello world in Python
</GOAL>

<CONTEXT>

</CONTEXT>

<TOOLS>
- run_command(command: string (required), timeout: integer (optional)): Run a restricted shell command
- web_search(query: string (required)): Search the web
</TOOLS>

<RULES>
Your ENTIRE response must be EXACTLY ONE of the following JSON objects.
Do NOT add any text, markdown fences, or comments.

To use a tool:
{"tool": "tool_name", "arguments": {"param1": "value1"}}

To finish the task:
{"done": true, "answer": "Your final answer"}

Never output both.
</RULES>

<TASK>
Say hello world in Python
</TASK>
EOF
)

# Escape for JSON string
PROMPT_ESCAPED=$(echo "$PROMPT" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")

# Call Ollama
RESPONSE=$(curl -s "$OLLAMA_URL/api/generate" \
  -d "{
    \"model\": \"$MODEL\",
    \"prompt\": $PROMPT_ESCAPED,
    \"stream\": false,
    \"options\": {\"temperature\": 0.0, \"num_predict\": 4096}
  }")

# Extract the "response" field
MODEL_OUTPUT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('response',''))")

# Check if empty
if [ -z "$MODEL_OUTPUT" ]; then
    echo "FAIL: Empty response from model"
    exit 1
fi

# Try to parse as JSON
JSON_CHECK=$(echo "$MODEL_OUTPUT" | python3 -c "
import sys,json
try:
    obj = json.load(sys.stdin)
    if 'done' in obj:
        print('DONE:' + obj.get('answer',''))
    elif 'tool' in obj:
        print('TOOL:' + obj.get('tool','') + ' ' + json.dumps(obj.get('arguments',{})))
    else:
        print('INVALID: JSON has no done/tool key')
except Exception as e:
    print('INVALID: not JSON - ' + str(e))
")

if [[ "$JSON_CHECK" == DONE:* ]]; then
    echo "OK: $JSON_CHECK"
    exit 0
elif [[ "$JSON_CHECK" == TOOL:* ]]; then
    echo "OK: $JSON_CHECK"
    exit 0
else
    echo "FAIL: $JSON_CHECK"
    echo "Raw output: $MODEL_OUTPUT"
    exit 1
fi
