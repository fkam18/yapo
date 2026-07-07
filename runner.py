#!/usr/bin/env python3
"""
Runner – executes a single job.
"""

import os, sys, json, subprocess, time, re
from conn_openai import generate as call_openai
from jobber import read_job_toml, move_job_folder, JOBS_DIR, acquire_lock, release_lock
from config import load_config, get_tool, get_server, get_model_for_type, get_yapo_root

YAPO_ROOT = get_yapo_root()
JOBS_DIR = os.path.join(YAPO_ROOT, 'jobs')
TOOL_CACHE = os.path.join(YAPO_ROOT, '.tool_cache.json')

# ---------- LLM / MCP helpers ----------
def call_backend(server, model, prompt, options):
    return call_openai(server, model, prompt, options)

def call_mcp_tool(tool, arguments):
    mcp_server_name = tool['mcp_server']
    mcp_tool_name = tool['mcp_tool']
    config = load_config()
    mcp_srv = None
    for s in config.get('mcp_servers', []):
        if s['name'] == mcp_server_name:
            mcp_srv = s
            break
    if not mcp_srv:
        raise Exception(f"MCP server {mcp_server_name} not found")

    protocol = mcp_srv.get('protocol', 'simple')

    if mcp_srv['transport'] == 'stdio':
        cmd = [mcp_srv['command']] + mcp_srv.get('args', [])
        env = os.environ.copy()
        if 'env' in mcp_srv:
            env.update(mcp_srv['env'])
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        if protocol == 'jsonrpc':
            request = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": mcp_tool_name,
                    "arguments": arguments
                },
                "id": 1
            }
        else:
            request = {"tool": mcp_tool_name, "arguments": arguments}

        try:
            out, err = proc.communicate(
                input=json.dumps(request),
                timeout=tool.get('timeout_seconds', 30)
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            raise Exception(f"MCP tool timed out after {tool.get('timeout_seconds', 30)}s")

        if err:
            print(f"MCP stderr: {err}", file=sys.stderr)

        if proc.returncode != 0:
            raise Exception(f"MCP tool error (code {proc.returncode}): {err}")

        if protocol == 'jsonrpc':
            try:
                response = json.loads(out)
                if 'result' in response:
                    return json.dumps(response['result'])
                elif 'error' in response:
                    raise Exception(f"JSON‑RPC error: {response['error']}")
                else:
                    lines = out.strip().split('\n')
                    for line in reversed(lines):
                        try:
                            obj = json.loads(line)
                            if 'result' in obj:
                                return json.dumps(obj['result'])
                        except:
                            continue
                    raise Exception("No valid JSON‑RPC result found")
            except json.JSONDecodeError:
                raise Exception(f"Invalid JSON‑RPC response: {out}")
        else:
            return out.strip()

    elif mcp_srv['transport'] == 'http':
        pass
    else:
        raise Exception(f"Unknown transport {mcp_srv['transport']}")


def inject_attachments(job_folder, context_text):
    """
    Read attachments from the job's assets/ folder and inject them into
    the context text. Text files are wrapped in <FILE> blocks. Images are
    noted as available for the model.
    Returns the modified context string.
    """
    assets_dir = os.path.join(job_folder, 'assets')
    if not os.path.isdir(assets_dir):
        return context_text

    text_extensions = {'.py', '.sh', '.txt', '.md', '.rs', '.js', '.ts', '.c', '.cpp',
                       '.h', '.java', '.go', '.rb', '.php', '.swift', '.kt', '.scala',
                       '.yaml', '.yml', '.toml', '.json', '.xml', '.csv', '.log', '.conf',
                       '.ini', '.cfg', '.env', '.css', '.html', '.sql', '.r', '.m', '.mm'}
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'}

    injected = ""
    for filename in sorted(os.listdir(assets_dir)):
        filepath = os.path.join(assets_dir, filename)
        ext = os.path.splitext(filename)[1].lower()
        
        if ext in text_extensions:
            try:
                with open(filepath, 'r', errors='replace') as f:
                    content = f.read()
                injected += f'\n<FILE path="{filename}">\n{content}\n</FILE>\n'
            except Exception:
                injected += f'\n<FILE path="{filename}">\n[Binary or unreadable file]\n</FILE>\n'
        elif ext in image_extensions:
            injected += f'\n<IMAGE path="{filename}">Image attached, available for analysis.</IMAGE>\n'
        else:
            size = os.path.getsize(filepath)
            injected += f'\n<FILE path="{filename}">File attached ({size} bytes, type: {ext})</FILE>\n'

    if injected:
        return context_text + "\n\nAttachments:\n" + injected
    return context_text


def build_prompt(job, config, turn_number=0):
    """Assemble the final prompt for main jobs, with dynamic convergence rules."""
    goal = job.get('prompt', '')
    context = ''
    ctx_path = os.path.join(JOBS_DIR, 'processing', str(job['qno']), 'context.txt')
    if os.path.exists(ctx_path):
        with open(ctx_path) as f:
            context = f.read()

    # Inject attachments into the context
    context = inject_attachments(os.path.join(JOBS_DIR, 'processing', str(job['qno'])), context)

    # Look up model config by type (not name)
    model_type = job.get('model_type', '')
    model_cfg = None
    for m in config.get('models', []):
        if m.get('type') == model_type:
            model_cfg = m
            break

    # Build tool list string
    tool_list_str = ''
    if model_cfg and model_cfg.get('tool_allowed', False):
        for tool in config.get('tools', []):
            if tool['name'] == 'route_prompt':
                continue
            tool_list_str += f"- {tool['name']}("
            params = tool.get('parameters', [])
            param_strs = []
            for p in params:
                req = 'required' if p.get('required', False) else 'optional'
                param_strs.append(f"{p['name']}: {p['type']} ({req})")
            tool_list_str += ', '.join(param_strs)
            tool_list_str += f"): {tool['description']}\n"
    else:
        tool_list_str = "(none)"

    # Dynamic convergence instruction
    if turn_number <= 2:
        convergence_note = "If the task is a straightforward coding or writing request that you can complete with your own knowledge, do it immediately without calling any tool."
    elif turn_number == 3:
        convergence_note = "You have called tools several times. You MUST now provide the final answer using the information you have. Do NOT call any more tools."
    else:
        convergence_note = "This is your LAST chance. Produce the final answer NOW. Do NOT call any tools."

    # Check if the model has a custom prompt template
    custom_template = model_cfg.get('prompt_template', '') if model_cfg else ''

    if custom_template:
        prompt = custom_template.replace('{{goal}}', goal)
        prompt = prompt.replace('{{context}}', context or '(none)')
        prompt = prompt.replace('{{tool_list}}', tool_list_str)
        prompt = prompt.replace('{{task}}', job.get('prompt', ''))
        prompt = prompt.replace('{{convergence_note}}', convergence_note)
        return prompt

    # Fallback: default XML template
    template = f"""<GOAL>
{goal}
</GOAL>

<CONTEXT>
{context}
</CONTEXT>

<TOOLS>
{tool_list_str}
</TOOLS>

<RULES>
Your ENTIRE response must be EXACTLY ONE of the following JSON objects.
Do NOT add any text, markdown fences, or comments.

- If you need information, use a tool:  
  {{
    "tool": "tool_name",
    "arguments": {{ "param1": "value1" }}
  }}

- Once you have the information (or if you already have enough), you MUST provide the final answer:  
  {{
    "done": true,
    "answer": "Your final answer (any text, code, or Markdown)."
  }}

IMPORTANT:
1. {convergence_note}
2. The run_command tool does NOT support shell operators like &&, >, |, etc. Use single commands only.
3. If the context already contains search results, do NOT call web_search again. Use those results to answer immediately.
4. Do NOT attempt to execute or test the code; just provide it.
Never output both formats. The "answer" field may contain multiple lines.
</RULES>

<TASK>
{job.get('prompt', '')}
</TASK>
"""
    return template


def propagate_tool_result(tool_qno, parent_qno, tool_name=''):
    lf = acquire_lock()
    try:
        tool_folder = os.path.join(JOBS_DIR, 'processing', str(tool_qno))
        output_path = os.path.join(tool_folder, 'output.txt')
        if not os.path.exists(output_path):
            raise Exception(f"Tool output not found: {output_path}")
        with open(output_path) as f:
            tool_output = f.read()

        for pst in ['ready', 'processing', 'pending']:
            parent_folder = os.path.join(JOBS_DIR, pst, str(parent_qno))
            if os.path.exists(parent_folder):
                ctx_path = os.path.join(parent_folder, 'context.txt')
                with open(ctx_path, 'a') as apf:
                    apf.write(f"\n[TOOL:{tool_name}]\n{tool_output}\n")
                sub_file = os.path.join(parent_folder, f'sub.{tool_qno}')
                if os.path.exists(sub_file):
                    os.remove(sub_file)
                remaining = [f for f in os.listdir(parent_folder) if f.startswith('sub.')]
                if not remaining:
                    move_job_folder(parent_qno, pst, 'ready')
                    print(f"Job {parent_qno} ready again (tool {tool_qno} finished)", file=sys.stderr)
                break
    finally:
        release_lock(lf)


def extract_json(text: str):
    text = text.strip()
    text = re.sub(r'\n?```\s*$', '', text)
    text = re.sub(r'^```[a-z]*\s*\n', '', text)
    try:
        return json.loads(text), text
    except json.JSONDecodeError:
        pass
    start = text.find('{')
    if start == -1:
        raise ValueError("No JSON object found")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                snippet = text[start:i+1]
                try:
                    return json.loads(snippet), snippet
                except json.JSONDecodeError:
                    raise ValueError(f"Invalid JSON: {snippet[:120]}...")
    raise ValueError("Unmatched braces in response")


def main():
    if len(sys.argv) != 2:
        print("Usage: runner.py <job_qno>", file=sys.stderr)
        sys.exit(1)
    qno = int(sys.argv[1])
    config = load_config()

    job_folder = os.path.join(JOBS_DIR, 'processing', str(qno))
    if not os.path.exists(job_folder):
        print(f"Job {qno} not in processing", file=sys.stderr)
        sys.exit(1)
    with open(os.path.join(job_folder, 'job.toml')) as f:
        job = json.load(f)
    job['qno'] = qno
    prompt_path = os.path.join(job_folder, 'prompt.txt')
    if os.path.exists(prompt_path):
        with open(prompt_path) as f:
            job['prompt'] = f.read().strip()
    else:
        job['prompt'] = ''

    # ----- tool job -----
    if job['type'] == 'tool':
        print(f"Job {qno} (tool) started: {job.get('tool_name','')}", file=sys.stderr)
        tool_call_path = os.path.join(job_folder, 'tool_call.json')
        with open(tool_call_path) as f:
            tool_req = json.load(f)
        tool_name = tool_req['tool']
        arguments = tool_req['arguments']
        tool = get_tool(tool_name)
        if not tool:
            print(f"Job {qno} failed: tool {tool_name} not found", file=sys.stderr)
            move_job_folder(qno, 'processing', 'error')
            sys.exit(1)
        try:
            result = call_mcp_tool(tool, arguments)
            with open(os.path.join(job_folder, 'output.txt'), 'w') as f:
                f.write(result)
            parent = job.get('parent', 0)
            if parent:
                propagate_tool_result(qno, parent, tool_name)
            move_job_folder(qno, 'processing', 'done')
            print(f"Job {qno} completed", file=sys.stderr)
        except Exception as e:
            print(f"Job {qno} failed: {e}", file=sys.stderr)
            move_job_folder(qno, 'processing', 'error')
        sys.exit(0)

    # ----- main job -----
    print(f"Job {qno} (main) started: {job['prompt'][:60]}", file=sys.stderr)

    # Resolve model_type → model_cfg (server name, template, options)
    model_type = job.get('model_type', '')
    if not model_type:
        print(f"Job {qno} routing...", file=sys.stderr)
        route_tool = get_tool('route_prompt')
        if not route_tool:
            print(f"Job {qno} failed: route_prompt tool not found", file=sys.stderr)
            move_job_folder(qno, 'processing', 'error')
            sys.exit(1)
        try:
            route_result = call_mcp_tool(route_tool, {"prompt": job['prompt']})
            model_type = route_result.strip().lower()
            if model_type in ['code', 'others', 'visual']:
                pass
            else:
                print(f"Job {qno} failed: router returned invalid classification '{model_type}'", file=sys.stderr)
                move_job_folder(qno, 'processing', 'error')
                sys.exit(1)
        except Exception as e:
            print(f"Job {qno} failed: router error {e}", file=sys.stderr)
            move_job_folder(qno, 'processing', 'error')
            sys.exit(1)
        job['model_type'] = model_type
        with open(os.path.join(job_folder, 'job.toml'), 'w') as f:
            json.dump(job, f)
        print(f"Job {qno} routed to type={model_type}", file=sys.stderr)

    # Look up model config by type
    model_cfg = None
    for m in config.get('models', []):
        if m.get('type') == model_type:
            model_cfg = m
            break
    if not model_cfg:
        print(f"Job {qno} failed: model type '{model_type}' not found in config", file=sys.stderr)
        move_job_folder(qno, 'processing', 'error')
        sys.exit(1)

    server_model_name = model_cfg['name']
    server_name = model_cfg['server']
    server = get_server(server_name)
    if not server:
        print(f"Job {qno} failed: server {server_name} not found", file=sys.stderr)
        move_job_folder(qno, 'processing', 'error')
        sys.exit(1)

    # compaction check (only when no sub jobs)
    sub_files = [f for f in os.listdir(job_folder) if f.startswith('sub.')]
    if not sub_files:
        ctx_path = os.path.join(job_folder, 'context.txt')
        if os.path.exists(ctx_path) and os.path.getsize(ctx_path) > config.get('compact_size_kb', 50) * 1024:
            print(f"Job {qno} compacting context...", file=sys.stderr)
            with open(ctx_path) as f:
                context_text = f.read()
            summarise_tool = get_tool('summarise_text')
            mem_write_tool = get_tool('mem_write')
            mem_read_tool = get_tool('mem_read')
            if all([summarise_tool, mem_write_tool, mem_read_tool]):
                summary = call_mcp_tool(summarise_tool, {"text": context_text, "max_points": 10})
                job_id = job.get('job_id', '')
                call_mcp_tool(mem_write_tool, {"text": f"{job_id}: {summary}"})
                memory = call_mcp_tool(mem_read_tool, {"query": job_id})
                new_qno = subprocess.check_output([sys.executable, 'jobber.py', 'create', '--type', 'main', '--state', 'ready', '--model-type', model_type, '--parent', str(job.get('parent', 0)), '--prompt-file', prompt_path])
                new_qno = int(new_qno.strip())
                clone_folder = os.path.join(JOBS_DIR, 'ready', str(new_qno))
                with open(os.path.join(clone_folder, 'context.txt'), 'w') as f:
                    f.write(memory)
                move_job_folder(qno, 'processing', 'done')
                print(f"Job {qno} compacted to job {new_qno}", file=sys.stderr)
                sys.exit(0)

    # Determine current turn number
    turn_number = 0
    ctx_path = os.path.join(job_folder, 'context.txt')
    if os.path.exists(ctx_path):
        with open(ctx_path) as f:
            turn_number = len([line for line in f if line.startswith('[TOOL:')])

    print(f"Job {qno} calling LLM {server_model_name} on {server_name}...", file=sys.stderr)
    prompt = build_prompt(job, config, turn_number)
    with open(os.path.join(job_folder, 'full_prompt.txt'), 'w') as f:
        f.write(prompt)
    options = {
        "temperature": model_cfg.get('temperature', 0.0),
        "num_predict": model_cfg.get('max_tokens', 4096),
    }
    if 'repeat_penalty' in model_cfg:
        options['repeat_penalty'] = model_cfg['repeat_penalty']
    if 'repeat_last_n' in model_cfg:
        options['repeat_last_n'] = model_cfg['repeat_last_n']
    if 'stop' in model_cfg:
        options['stop'] = model_cfg['stop']

    try:
        response = call_backend(server, server_model_name, prompt, options)
        with open(os.path.join(job_folder, 'output.txt'), 'w') as f:
            f.write(response)

        try:
            output_json, cleaned_text = extract_json(response)
        except ValueError as e:
            print(f"Job {qno} failed: invalid JSON output - {e}", file=sys.stderr)
            move_job_folder(qno, 'processing', 'error')
            sys.exit(1)

        with open(os.path.join(job_folder, 'output.txt'), 'w') as f:
            f.write(cleaned_text)

        if 'tool' in output_json:
            tool_name = output_json['tool']
            arguments = output_json['arguments']

            tool_call_history = []
            ctx_path = os.path.join(job_folder, 'context.txt')
            if os.path.exists(ctx_path):
                with open(ctx_path) as f:
                    tool_call_history = [line for line in f if line.startswith('[TOOL:')]
            if len(tool_call_history) >= 5:
                print(f"Job {qno} forced done after {len(tool_call_history)} tool calls", file=sys.stderr)
                output_json = {"done": True, "answer": "Task completed. See context for details."}
                with open(os.path.join(job_folder, 'output.txt'), 'w') as f:
                    f.write(json.dumps(output_json))
                move_job_folder(qno, 'processing', 'done')
                parent = job.get('parent', 0)
                if parent:
                    subprocess.run([sys.executable, 'jobber.py', 'cleanup', str(parent)])
                sys.exit(0)

            tool_json_str = json.dumps({"tool": tool_name, "arguments": arguments})
            child_qno = subprocess.check_output([
                sys.executable, 'jobber.py', 'create',
                '--type', 'tool',
                '--state', 'ready',
                '--parent', str(qno),
                '--tool-name', tool_name,
                '--tool-json', tool_json_str
            ]).decode().strip()
            with open(os.path.join(job_folder, f'sub.{child_qno}'), 'w') as f:
                pass
            move_job_folder(qno, 'processing', 'pending')
            print(f"Job {qno} pending – created tool child {child_qno} ({tool_name})", file=sys.stderr)
        elif 'done' in output_json:
            move_job_folder(qno, 'processing', 'done')
            print(f"Job {qno} completed", file=sys.stderr)
            parent = job.get('parent', 0)
            if parent:
                subprocess.run([sys.executable, 'jobber.py', 'cleanup', str(parent)])
        else:
            print(f"Job {qno} failed: JSON without done/tool key", file=sys.stderr)
            move_job_folder(qno, 'processing', 'error')
    except Exception as e:
        print(f"Job {qno} failed: {e}", file=sys.stderr)
        move_job_folder(qno, 'processing', 'error')

if __name__ == '__main__':
    main()
