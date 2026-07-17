**Current Release:** v2.3.0

# Yapo – Yet Another Personal Orchestrator

Yapo is a home‑lab LLM job orchestrator. It manages stateless LLM jobs through a folder‑based job pool, routes prompts to the right model, and provides a set of tools (memory, summarisation, web search, shell commands, **and now persistent file operations**) via MCP servers. It supports GPU energy management with on‑demand Wake‑on‑LAN and automatic suspend.

Yapo is designed to run **24×7 as a Docker container** on a headless server. All interaction — job submission, queue monitoring, config reload, and log inspection — happens through the built‑in **Web UI** and **REST API** on port 3388. The original CLI tools (`init.py`, `catjob.py`) remain available for development use.

---

## Features

* **Docker deployment** – Single‑command Ansible deploy to a remote server. Container auto‑restarts, uses host networking for WoL, and mounts secrets/config at runtime.
* **Web dashboard** – Submit jobs (with file attachments), view all job queues with pagination, inspect job details (including tool‑call requests), copy output, and toggle raw/answer views. Auto‑refreshes every 2 seconds.
* **REST API** – Full job lifecycle management via HTTP. Submit jobs, wait for completion, download job folders, delete jobs (single or bulk with recursive child cleanup), reload config, toggle debug logging, and stream scheduler logs. **New in v2.3: workspace file management** – upload, download, list, and delete files in the LLM’s persistent workspace volume directly through the API. See the [API Reference](#api-reference) below.
* **File attachments** – Attach text files, source code, or images to any job via the dashboard or API. Text files are injected into the prompt; images are passed to vision models.
* **Persistent workspace** – A Docker named volume is mounted at `/ws` inside the Yapo container. The LLM can read, write, list, create directories, and search file contents using new MCP filesystem tools. The dashboard exposes REST endpoints for manual upload/download and sync, allowing you to pre‑load files for the LLM or retrieve its output.
* **Folder‑based job queue** – Jobs move through `ready → processing → pending → done / error` states. All state changes are atomic and serialised.
* **Automatic prompt routing** – A small router model (or a manual `--mtype` flag) sends tasks to the right LLM (`code`, `others`, or `visual`).
* **Per‑model configuration** – Each model can define its own `system_prompt`, `max_turns` (tool‑call cycle limit), and extra API‑level parameters such as `chat_template_kwargs`. This provides fine‑grained control over LLM behaviour.
* **MCP tools** – Memory (write / read / summarise), web search (SearXNG), restricted shell commands, and **filesystem operations**. Add your own tools by registering an MCP server.
* **Dynamic convergence** – A per‑turn convergence note escalates softly as the job approaches its `max_turns` limit, then forces a final answer. After the first turn, the original task is kept only in the conversation history – the follow‑up message contains just the convergence note, avoiding repetitive tool‑call loops.
* **GPU energy management** – Per‑server power schedules, Wake‑on‑LAN when a job is ready, automatic SSH‑based suspend after idle timeout, and schedule‑window support.
* **OpenAI‑compatible backend** – Works with Ollama, llama.cpp, and any server that speaks `/v1/chat/completions`. Supports multimodal image inputs for vision models.
* **Runtime config reload** – Edit `config.toml` on the server and send a SIGHUP (or call `POST /api/reload`) to apply changes without restarting.

---

## Deployment (Docker + Ansible)

1. **Configure your laptop** — edit `config.toml` with your server IPs, model names, and paths.
2. **Build the Docker image:**
```bash
cd docker
./build.sh

    Deploy to Server:

bash

./deploy-to-app1.sh

    Access the dashboard at http://<server-ip>:3388.

Development (CLI)

For local development and testing without Docker:

    Clone and set up a venv:

bash

git clone https://github.com/fkam18/yapo.git
cd yapo
python3 -m venv venv
source venv/bin/activate
pip install chromadb

    Configure — copy config.example.toml to config.toml and fill in your details.

    Create the job folders:

bash

mkdir -p ~/yapo/jobs/{ready,processing,pending,done,error}

    Start the scheduler:

bash

python3 yapo.py

    Submit a job:

bash

python3 init.py "Write a Python function to sort a list"

    Inspect the result:

bash

python3 catjob.py <queue-number>

API Reference

All endpoints are available at http://<server>:3388.
Job Submission & Retrieval
Method	Endpoint	Description
POST	/api/submit	Submit a new job (with optional attachments, RAG, time constraints)
GET	/api/job/<qno>	Get job details and output
GET	/api/job/<qno>?wait=true&timeout=300	Block until job completes or timeout
GET	/api/job/<qno>/download	Download job folder as tar.gz
Job Listing & Deletion
Method	Endpoint	Description
GET	/api/tree	Full job hierarchy with parent/child relationships
DELETE	/api/job/<qno>	Delete a job and all its descendants recursively
DELETE	/api/jobs?from=X&to=Y&state=done	Bulk‑delete jobs in a range
Workspace File Management (new in v2.3)
Method	Endpoint	Description
GET	/api/ws/list?path=<rel>	List directory contents in the workspace
GET	/api/ws/download?path=<rel>	Download a file from the workspace
POST	/api/ws/upload	Upload a file (JSON body with base64 content)
POST	/api/ws/mkdir	Create a directory in the workspace
DELETE	/api/ws/delete?path=<rel>	Delete a file or empty directory
Config & Monitoring
Method	Endpoint	Description
GET	/api/config	Get current config.toml as JSON
POST	/api/reload	Reload config (sends SIGHUP to scheduler)
PATCH	/api/config	Update a runtime config key (e.g. toggle debug)
GET	/api/logs?lines=99999	Get all log lines then delete them from server
GET	/api/debug/openai	Download OpenAI API debug log
GET	/api/health	Health check (returns {"status":"ok"})
Web UI
Method	Endpoint	Description
GET	/	Interactive web dashboard
GET	/api/queues	HTML fragment for auto‑refresh
Directory Layout
text

yapo/                        ← project source
├── docker/                  ← Docker & Ansible deployment files
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── build.sh
│   ├── deploy-to-app1.sh
│   ├── deploy.yml
│   ├── inventory.ini
│   ├── config.toml.j2
│   ├── convert-config.py
│   ├── entrypoint.sh
│   └── requirements.txt
├── yapo.py                  ← scheduler main loop
├── runner.py                ← single job executor (OpenAI native tool‑calling)
├── jobber.py                ← job CRUD operations
├── init.py                  ← CLI job submission (dev)
├── dashboard.py             ← Web UI + REST API server (now includes workspace endpoints)
├── config.py                ← configuration loader
├── conn_openai.py           ← OpenAI‑compatible backend
├── yapo_mcp.py              ← MCP server (router, memory, summarise)
├── shell_mcp.py             ← MCP server (restricted shell)
├── web_search_mcp.py        ← MCP server (SearXNG wrapper)
├── filesystem_mcp.py        ← MCP server (workspace file operations) [new]
├── memory.py                ← ChromaDB vector memory
├── summarise.py             ← document / turn summarisation
├── catjob.py                ← CLI job inspector
├── catanswer.py             ← extract answer from job output
├── dashboard.theme          ← dashboard CSS theme
├── config.toml.example      ← sample configuration
└── spec15.txt               ← full design specification (v15) [updated]

License

MIT
