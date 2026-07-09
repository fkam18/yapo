# Enable debug
curl -X PATCH http://app1.alt:3388/api/config \
  -H "Content-Type: application/json" \
  -d '{"key":"CONN_OPENAI_DEBUG","value":"true"}'

# Submit a test job to generate log entries
curl -X POST http://app1.alt:3388/api/submit \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Say hello","mtype":"others"}'

# Wait a few seconds, then download the debug log
sleep 10
curl -O http://app1.alt:3388/api/debug/openai
cat openai.txt | head -50
