** Current Release: v0.13.0 **

# Yapo – Yet Another Personal Orchestrator

Yapo is a home‑lab LLM job orchestrator. It manages stateless LLM jobs through a folder‑based job pool, routes prompts to the right model, and provides a set of tools (memory, summarisation, web search, shell commands) via MCP servers. It supports GPU energy management with on‑demand Wake‑on‑LAN and automatic suspend.

## Features

- **Folder‑based job queue** – Jobs move through `ready → processing → pending → done / error` states. All state changes are atomic and serialised.
- **Automatic prompt routing** – A small router model (or a manual `--mtype` flag) sends tasks to the right LLM (`code`, `others`, or `visual`).
- **MCP tools** – Memory (write / read / summarise), web search (SearXNG), and restricted shell commands. Add your own tools by registering an MCP server in `config.toml`.
- **Dynamic prompt convergence** – The system gently nudges the LLM toward a final answer, and a hard loop‑guard prevents infinite tool‑call cycles.
- **GPU energy management** – Wake‑on‑LAN when a job is ready, automatic SSH‑based suspend after an idle timeout, and schedule‑window support.
- **OpenAI‑compatible backend** – Works with Ollama, llama.cpp, and any other server that speaks `/v1/chat/completions`.
- **Web dashboard** – View all job queues and inspect job details on `http://localhost:3388` (auto‑refreshes).
- **CLI tools** – `catjob.py` to inspect job output, `catanswer.py` to extract answers as plain text.

## Quick Start

1. **Clone the repository**
   ```bash
   git clone https://github.com/fkam18/yapo.git
   cd yapo
