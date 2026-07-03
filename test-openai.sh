curl http://192.168.0.158:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer no-key" \
  -d '{
    "model": "qwen",
    "messages": [
      {
        "role": "user",
        "content": "write a story about hong kong"
      }
    ],
    "temperature": 0.7
  }'
