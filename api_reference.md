# API Reference

Here’s the full API reference with example requests and their expected JSON responses (or other formats).

> **Note:** Replace `HOST` with your actual server address (e.g., `app1.alt:3388` or `localhost:3388`).

---

## Job Submission & Retrieval

### `POST /api/submit`

Submit a new job to the queue.

**Example Request:**

```bash
curl -X POST http://HOST/api/submit \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Write a Python hello world",
    "mtype": "code",
    "name": "hello-job",
    "start_after": "22:00",
    "max_duration": 600,
    "rags": ["mem_read:python"],
    "attachments": []
  }'
```

**Responses:**

* **Success (200 OK):**
  ```json
  {"success": true, "qno": "42"}
  ```

* **Error (200 OK with error field):**
  ```json
  {"error": "some error message"}
  ```

---

### `GET /api/job/<qno>`

Retrieve status and details of a specific job by its queue number.

**Example Request:**

```bash
curl http://HOST/api/job/42
```

**Responses:**

* **Success (200 OK):**
  ```json
  {
    "state": "done",
    "name": "hello-job",
    "job_type": "main",
    "model_type": "code",
    "model_name": "devstral2-24b",
    "tool_name": "",
    "start_after": "22:00",
    "max_job_duration": 600,
    "output": "{\"role\":\"assistant\",\"content\":\"print('hello')\\n\"}",
    "tool_call": null
  }
  ```
  *If the job has a tool call, `tool_call` contains the full tool‑call object from `tool_call.json`. If `output.txt` is not present, `output` is `null`.*

* **Job Not Found (200 OK):**
  ```json
  {"error": "Job not found"}
  ```

---

### `GET /api/job/<qno>?wait=true&timeout=300`

Block and wait for job completion or timeout.

**Example Request:**

```bash
curl "http://HOST/api/job/42?wait=true&timeout=120"
```

**Responses:**

* **Success (200 OK):** Same schema as `GET /api/job/<qno>` when complete.
* **Timeout (200 OK):**
  ```json
  {
    "state": "processing",
    "timed_out": true
  }
  ```

---

### `GET /api/job/<qno>/download`

Download job assets/results archive.

**Example Request:**

```bash
curl -O http://HOST/api/job/42/download
```

**Responses:**

* **Success:** Binary `tar.gz` file (not JSON).
* **Error (404 Not Found):**
  ```json
  {"error": "Job not found"}
  ```

---

## Job Listing & Deletion

### `GET /api/tree`

Get the full hierarchy/tree of jobs.

**Example Request:**

```bash
curl http://HOST/api/tree
```

**Responses:**

* **Success (200 OK):**
  ```json
  {
    "1": {
      "state": "done",
      "job_type": "main",
      "name": "my-job",
      "model_type": "code",
      "tool_name": "",
      "parent": 0,
      "children": [2, 3]
    },
    "2": { ... },
    "3": { ... }
  }
  ```

---

### `DELETE /api/job/<qno>`

Delete a specific job by queue number.

**Example Request:**

```bash
curl -X DELETE http://HOST/api/job/42
```

**Responses:**

* **Success (200 OK):**
  ```json
  {"success": true, "deleted": ["42", "43", "44"], "count": 3}
  ```

* **Not Found (404 Not Found):**
  ```json
  {"error": "Job not found"}
  ```

---

### `DELETE /api/jobs?from=X&to=Y&state=done`

Delete a range of jobs by state.

**Example Request:**

```bash
curl -X DELETE "http://HOST/api/jobs?from=10&to=50&state=done"
```

**Responses:**

* **Success (200 OK):**
  ```json
  {"success": true, "deleted": ["10","12","15"], "count": 3}
  ```

---

## Workspace File Management

*All paths are relative to `/ws` inside the container.*

### `GET /api/ws/list?path=<rel>`

List files and directories in a workspace path.

**Example Request:**

```bash
curl "http://HOST/api/ws/list?path=projects"
```

**Responses:**

* **Success (200 OK):**
  ```json
  {
    "path": "projects",
    "entries": [
      {"name": "readme.txt", "type": "file", "size": 1024},
      {"name": "src", "type": "directory", "size": 0}
    ]
  }
  ```

---

### `GET /api/ws/download?path=<rel>`

Download raw file content from workspace.

**Example Request:**

```bash
curl "http://HOST/api/ws/download?path=projects/readme.txt"
```

**Responses:**

* **Success:** File content as raw text (not JSON).
* **Error:** `"File not found"` text with appropriate HTTP status.

---

### `POST /api/ws/upload`

Upload a base64-encoded file to the workspace.

**Example Request:**

```bash
curl -X POST http://HOST/api/ws/upload \
  -H "Content-Type: application/json" \
  -d '{
    "path": "projects/notes.txt",
    "content": "SGVsbG8sIHdvcmxkIQ=="
  }'
```

**Responses:**

* **Success (200 OK):**
  ```json
  {"success": true, "path": "projects/notes.txt"}
  ```

---

### `POST /api/ws/mkdir`

Create a new directory in the workspace.

**Example Request:**

```bash
curl -X POST http://HOST/api/ws/mkdir \
  -H "Content-Type: application/json" \
  -d '{"path": "projects/new-folder"}'
```

**Responses:**

* **Success (200 OK):**
  ```json
  {"success": true}
  ```

---

### `DELETE /api/ws/delete?path=<rel>`

Delete a file or folder from the workspace.

**Example Request:**

```bash
curl -X DELETE "http://HOST/api/ws/delete?path=projects/notes.txt"
```

**Responses:**

* **Success (200 OK):**
  ```json
  {"success": true}
  ```

---

## Config & Monitoring

### `GET /api/config`

Retrieve server configuration.

**Example Request:**

```bash
curl http://HOST/api/config
```

**Responses:**

* **Success (200 OK):**
  ```json
  {
    "workspace": "/home/fkam/apps",
    "yapo_root": "/home/fkam/yapo",
    "database": { "path": "...", "collection": "..." },
    "compact_size_kb": 50,
    "max_job_duration": 900,
    "servers": [ ... ],
    "models": [ ... ],
    "mcp_servers": [ ... ],
    "tools": [ ... ]
  }
  ```

---

### `POST /api/reload`

Trigger a configuration reload signal.

**Example Request:**

```bash
curl -X POST http://HOST/api/reload
```

**Responses:**

* **Success (200 OK):**
  ```json
  {"success": true, "message": "Config reload signal sent"}
  ```

* **Error (500 Internal Server Error):**
  ```json
  {"error": "some error"}
  ```

---

### `PATCH /api/config`

Update configuration dynamic flags/keys.

**Example Request:**

```bash
curl -X PATCH http://HOST/api/config \
  -H "Content-Type: application/json" \
  -d '{"key": "CONN_OPENAI_DEBUG", "value": "true"}'
```

**Responses:**

* **Success (200 OK):**
  ```json
  {"success": true, "CONN_OPENAI_DEBUG": "true"}
  ```

* **Invalid Key (400 Bad Request):**
  ```json
  {"error": "Unknown config key: BAD_KEY"}
  ```

---

### `GET /api/logs?lines=200`

Fetch trailing server log lines.

**Example Request:**

```bash
curl "http://HOST/api/logs?lines=200"
```

**Responses:**

* **Success:** Plain text log lines (not JSON).  
  *Note: The log buffer is cleared after reading.*

---

### `GET /api/health`

Health check endpoint.

**Example Request:**

```bash
curl http://HOST/api/health
```

**Responses:**

* **Success (200 OK):**
  ```json
  {"status": "ok"}
  ```

---

## Memory Direct Access

### `POST /api/mem/write`

Write text memory entries directly into the vector/RAG memory.

**Example Request:**

```bash
curl -X POST http://HOST/api/mem/write \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Yapo is a home‑lab LLM orchestrator.",
    "prefix": "project-info"
  }'
```

**Responses:**

* **Success (200 OK):**
  ```json
  {"success": true, "message": "Stored 1 lines.\n"}
  ```

---

### `GET /api/mem/read?key=<query>&top_k=5&compact=true&del=false`

Query raw memory entries.

**Example Request:**

```bash
curl "http://HOST/api/mem/read?key=Yapo&top_k=5&compact=true&del=false"
```

**Responses:**

* **Success:** Plain text listing of memory entries (raw output of `mem_read`), e.g.:
  ```text
  - Yapo is a home‑lab LLM orchestrator.
  - Yapo manages stateless LLM jobs...
  ```

---

## Web UI Fragment

### `GET /api/queues`

Fetch HTML fragment for dashboard monitoring.

**Example Request:**

```bash
curl http://HOST/api/queues
```

**Responses:**

* **Success:** HTML fragment (not JSON), used internally for dashboard auto‑refresh.

---

*Note: All endpoints return JSON unless explicitly noted as plain text or binary.*
