#!/usr/bin/env python3
"""
Runner – executes a single job (spec13 – OpenAI structured messages).
"""

import os, sys, json, subprocess, time, re, base64, uuid
from conn_openai import generate as call_openai
from jobber import read_job_toml, move_job_folder, JOBS_DIR, acquire_lock, release_lock
from config import load_config, get_tool, get_server, get_model_for_type, get_yapo_root
from json_repair import repair_json

YAPO_ROOT = get_yapo_root()
JOBS_DIR = os.path.join(YAPO_ROOT, 'jobs')
TOOL_CACHE = os.path.join(YAPO_ROOT, '.tool_cache.json')

# ---------- LLM / MCP helpers ----------
def call_backend(server, model, messages, options, tools=None, image_data=None):
    """Wrapper that passes tools array to the OpenAI connector."""
    return call_openai(server, model, messages, options, tools, image_data)

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


def collect_image_data(job_folder):
    """Collect base64-encoded images from the job's assets/ folder."""
    assets_dir = os.path.join(job_folder, 'assets')
    if not os.path.isdir(assets_dir):
        return []
    
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    images = []
    for filename in sorted(os.listdir(assets_dir)):
        ext = os.path.splitext(filename)[1].lower()
        if ext in image_exts:
            filepath = os.path.join(assets_dir, filename)
            with open(filepath, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
                mime = 'image/jpeg' if ext in ('.jpg', '.jpeg') else f'image/{ext[1:]}'
                images.append({'data': b64, 'mime': mime})
    return images


def inject_attachments_into_message(job_folder, base_content):
    """Return a user message content (string or multimodal array) with attachments."""
    assets_dir = os.path.join(job_folder, 'assets')
    if not os.path.isdir(assets_dir):
        return base_content

    text_extensions = {'.py', '.sh', '.txt', '.md', '.rs', '.js', '.ts', '.c', '.cpp',
                       '.h', '.java', '.go', '.rb', '.php', '.swift', '.kt', '.scala',
                       '.yaml', '.yml', '.toml', '.json', '.xml', '.csv', '.log', '.conf',
                       '.ini', '.cfg', '.env', '.css', '.html', '.sql', '.r', '.m', '.mm'}
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'}

    text_parts = []
    image_parts = []
    has_assets = False
    for filename in sorted(os.listdir(assets_dir)):
        filepath = os.path.join(assets_dir, filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext in text_extensions:
            try:
                with open(filepath, 'r', errors='replace') as f:
                    content = f.read()
                text_parts.append(f'<FILE path="{filename}">\n{content}\n</FILE>')
                has_assets = True
            except Exception:
                text_parts.append(f'<FILE path="{filename}">\n[Binary or unreadable file]</FILE>')
                has_assets = True
        elif ext in image_extensions:
            with open(filepath, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
            mime = 'image/jpeg' if ext in ('.jpg', '.jpeg') else f'image/{ext[1:]}'
            image_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
            has_assets = True
        else:
            size = os.path.getsize(filepath)
            text_parts.append(f'<FILE path="{filename}">File attached ({size} bytes, type: {ext})</FILE>')
            has_assets = True

    if not has_assets:
        return base_content

    full_text = base_content + "\n\nAttachments:\n" + "\n".join(text_parts)
    if image_parts:
        multimodal = [{"type": "text", "text": full_text}]
        multimodal.extend(image_parts)
        return multimodal
    else:
        return full_text


def build_payload(job, config, turn_number=0, max_turns=5):
    """
    Build an OpenAI-compatible payload (spec13) for a main job.
    Returns (messages, user_message_content, tools, options_dict).
    """
    qno = job['qno']
    job_folder = os.path.join(JOBS_DIR, 'processing', str(qno))

    # Load model config
    model_type = job.get('model_type', '')
    model_cfg = None
    for m in config.get('models', []):
        if m.get('type') == model_type:
            model_cfg = m
            break
    if not model_cfg:
        raise Exception(f"Model type '{model_type}' not found in config")

    system_prompt = model_cfg.get('system_prompt', 'You are a helpful assistant.')
    tool_allowed = model_cfg.get('tool_allowed', False)

    # Build tool definitions
    tools = None
    if tool_allowed:
        tools = []
        for tool in config.get('tools', []):
            if tool['name'] == 'route_prompt':
                continue
            params = tool.get('parameters', [])
            properties = {}
            required = []
            for p in params:
                properties[p['name']] = {"type": p.get('type', 'string'), "description": p.get('description', '')}
                if p.get('required', False):
                    required.append(p['name'])
            tools.append({
                "type": "function",
                "function": {
                    "name": tool['name'],
                    "description": tool.get('description', ''),
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required
                    }
                }
            })

    # Load conversation history
    conv_path = os.path.join(job_folder, 'conversation.json')
    if os.path.exists(conv_path):
        with open(conv_path) as f:
            conversation = json.load(f)
    else:
        conversation = []

    # Build messages array
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation)

    # Current user task
    prompt_path = os.path.join(job_folder, 'prompt.txt')
    if os.path.exists(prompt_path):
        with open(prompt_path) as f:
            task = f.read().strip()
    else:
        task = job.get('prompt', '')

    # Convergence note – now scaled by max_turns
    if turn_number < max_turns - 1:
        convergence_note = "If the task is a straightforward coding or writing request that you can complete with your own knowledge, do it immediately without calling any tool."
    elif turn_number == max_turns - 1:
        convergence_note = "You have called tools several times. You MUST now provide the final answer using the information you have. Do NOT call any more tools."
    else:
        convergence_note = "This is your LAST chance. Produce the final answer NOW. Do NOT call any tools."

    if turn_number == 0:
        user_message_content = task + "\n\n" + convergence_note
    else:
        user_message_content = convergence_note

    # Inject attachments into user message
    user_message_content = inject_attachments_into_message(job_folder, user_message_content)

    # Build options dict from model config
    options = {}
    for key in ['temperature', 'max_tokens', 'top_k', 'top_p', 'min_p', 
                'repeat_penalty', 'repeat_last_n', 'presence_penalty', 'frequency_penalty',
                'seed', 'stop', 'chat_template_kwargs']:
        if key in model_cfg:
            options[key] = model_cfg[key]

    return messages, user_message_content, tools, options


def extract_json_from_content(text: str):
    """Legacy JSON extraction for done/tool parsing (not used for tool calls in spec13)."""
    text = text.strip()
    text = re.sub(r'\n?```\s*$', '', text)
    text = re.sub(r'^```[a-z]*\s*\n', '', text)
    try:
        return json.loads(text), text
    except json.JSONDecodeError:
        try:
            repaired = repair_json(text)
            return json.loads(repaired), repaired
        except Exception:
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

    # ----- tool job -----
    if job['type'] == 'tool':
        print(f"Job {qno} (tool) started: {job.get('tool_name','')}", file=sys.stderr)
        tool_call_path = os.path.join(job_folder, 'tool_call.json')
        with open(tool_call_path) as f:
            tool_call_obj = json.load(f)
        tool_name = tool_call_obj['function']['name']
        arguments = json.loads(tool_call_obj['function']['arguments'])
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
                propagate_tool_result(qno, parent, tool_name, tool_call_obj['id'])
            move_job_folder(qno, 'processing', 'done')
            print(f"Job {qno} completed", file=sys.stderr)
        except Exception as e:
            print(f"Job {qno} failed: {e}", file=sys.stderr)
            move_job_folder(qno, 'processing', 'error')
        sys.exit(0)

    # ----- main job -----
    print(f"Job {qno} (main) started: {job.get('prompt','')[:60]}", file=sys.stderr)

    # Routing if needed
    model_type = job.get('model_type', '')
    if not model_type:
        print(f"Job {qno} routing...", file=sys.stderr)
        route_tool = get_tool('route_prompt')
        if not route_tool:
            print(f"Job {qno} failed: route_prompt tool not found", file=sys.stderr)
            move_job_folder(qno, 'processing', 'error')
            sys.exit(1)
        try:
            prompt_path = os.path.join(job_folder, 'prompt.txt')
            if os.path.exists(prompt_path):
                with open(prompt_path) as f:
                    prompt_text = f.read().strip()
            else:
                prompt_text = job.get('prompt', '')
            route_result = call_mcp_tool(route_tool, {"prompt": prompt_text})
            model_type = route_result.strip().lower()
            if model_type not in ['code', 'others', 'visual']:
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

    # ──── MODEL CONFIG LOOKUP (must happen before payload building) ────
    model_cfg = None
    for m in config.get('models', []):
        if m.get('type') == model_type:
            model_cfg = m
            break
    if not model_cfg:
        print(f"Job {qno} failed: model type '{model_type}' not found in config", file=sys.stderr)
        move_job_folder(qno, 'processing', 'error')
        sys.exit(1)

    max_turns = model_cfg.get('max_turns', 5)

    server_model_name = model_cfg['name']
    server_name = model_cfg['server']
    server = get_server(server_name)
    if not server:
        print(f"Job {qno} failed: server {server_name} not found", file=sys.stderr)
        move_job_folder(qno, 'processing', 'error')
        sys.exit(1)

    # ──── DETERMINE TURN NUMBER ────
    conv_path = os.path.join(job_folder, 'conversation.json')
    conversation = []
    if os.path.exists(conv_path):
        with open(conv_path) as f:
            conversation = json.load(f)
    turn_number = sum(1 for msg in conversation if msg['role'] == 'tool')

    # ──── BUILD PAYLOAD ────
    messages, user_msg_content, tools, options = build_payload(job, config, turn_number, max_turns)

    # Compaction check (when no sub‑jobs and conversation.json is large)
    sub_files = [f for f in os.listdir(job_folder) if f.startswith('sub.')]
    if not sub_files:
        conv_size = os.path.getsize(conv_path) if os.path.exists(conv_path) else 0
        if conv_size > config.get('compact_size_kb', 50) * 1024:
            print(f"Job {qno} compacting context...", file=sys.stderr)
            text_parts = []
            for msg in conversation:
                if msg['role'] in ('user', 'assistant') and msg.get('content'):
                    text_parts.append(msg['content'])
            context_text = "\n".join(text_parts)
            summarise_tool = get_tool('summarise_text')
            mem_write_tool = get_tool('mem_write')
            mem_read_tool = get_tool('mem_read')
            if all([summarise_tool, mem_write_tool, mem_read_tool]):
                summary = call_mcp_tool(summarise_tool, {"text": context_text, "max_points": 10})
                job_id = job.get('job_id', '')
                call_mcp_tool(mem_write_tool, {"text": f"{job_id}: {summary}"})
                memory = call_mcp_tool(mem_read_tool, {"query": job_id})
                new_qno = subprocess.check_output([sys.executable, 'jobber.py', 'create', '--type', 'main', '--state', 'ready', '--model-type', model_type, '--parent', str(job.get('parent', 0)), '--prompt-file', os.path.join(job_folder, 'prompt.txt')])
                new_qno = int(new_qno.strip())
                clone_folder = os.path.join(JOBS_DIR, 'ready', str(new_qno))
                init_conv = [{"role": "system", "content": model_cfg.get('system_prompt', '')},
                             {"role": "user", "content": f"[Compacted memory]\n{memory}"}]
                with open(os.path.join(clone_folder, 'conversation.json'), 'w') as f:
                    json.dump(init_conv, f)
                move_job_folder(qno, 'processing', 'done')
                print(f"Job {qno} compacted to job {new_qno}", file=sys.stderr)
                sys.exit(0)

    # Add current user message to messages array for sending
    messages.append({"role": "user", "content": user_msg_content})

    # Save payload for debugging
    full_payload = {
        "model": server_model_name,
        "messages": messages,
        "temperature": options.get('temperature', 0.0),
        "max_tokens": options.get('max_tokens', 4096),
        "stream": False
    }
    if tools:
        full_payload["tools"] = tools
    for k in ['top_k', 'top_p', 'min_p', 'repeat_penalty', 'repeat_last_n', 'presence_penalty', 'frequency_penalty', 'seed', 'stop', 'chat_template_kwargs']:
        if k in options:
            full_payload[k] = options[k]
    with open(os.path.join(job_folder, 'full_payload.json'), 'w') as f:
        json.dump(full_payload, f, indent=2)

    # Collect images (for multimodal models)
    image_data = collect_image_data(job_folder)

    print(f"Job {qno} calling LLM {server_model_name} on {server_name}...", file=sys.stderr)
    try:
        # Call backend – returns the full assistant message object (with possible tool_calls)
        assistant_message = call_backend(server, server_model_name, messages, options, tools, image_data if image_data else None)

        # Save raw assistant message to output.txt (for debugging)
        with open(os.path.join(job_folder, 'output.txt'), 'w') as f:
            json.dump(assistant_message, f, indent=2)

        # ── spec13: handle both native tool_calls and text‑based tool calls ──
        native_tool_calls = assistant_message.get('tool_calls', [])
        if not native_tool_calls:
            # Fallback: try to parse the content as a legacy JSON tool call
            content = assistant_message.get('content', '')
            if content and content.strip():
                try:
                    cleaned = content.strip()
                    if cleaned.startswith('```'):
                        first_nl = cleaned.find('\n')
                        if first_nl != -1:
                            cleaned = cleaned[first_nl+1:]
                        if cleaned.endswith('```'):
                            cleaned = cleaned[:-3].strip()
                    parsed = json.loads(cleaned)
                    if 'tool' in parsed and 'arguments' in parsed:
                        call_id = 'call_' + uuid.uuid4().hex[:12]
                        native_tool_calls = [{
                            'id': call_id,
                            'type': 'function',
                            'function': {
                                'name': parsed['tool'],
                                'arguments': json.dumps(parsed['arguments'])
                            }
                        }]
                        # Rewrite assistant message to include tool_calls
                        assistant_message['tool_calls'] = native_tool_calls
                        assistant_message['content'] = None
                except (json.JSONDecodeError, ValueError):
                    pass  # not a JSON tool call, treat as normal content

        # Update conversation history
        # 1. Append the user message we just sent
        conversation.append({"role": "user", "content": user_msg_content})
        # 2. Append assistant message
        conversation.append(assistant_message)
        with open(conv_path, 'w') as f:
            json.dump(conversation, f, indent=2)

        # Handle tool calls
        if native_tool_calls:
            tool_msg_count = sum(1 for msg in conversation if msg['role'] == 'tool')
            if tool_msg_count >= max_turns:
                print(f"Job {qno} forced done after {tool_msg_count} tool turns (limit {max_turns})", file=sys.stderr)
                conversation.append({"role": "assistant", "content": "Task completed. See context for details."})
                with open(conv_path, 'w') as f:
                    json.dump(conversation, f)
                move_job_folder(qno, 'processing', 'done')
                parent = job.get('parent', 0)
                if parent:
                    subprocess.run([sys.executable, 'jobber.py', 'cleanup', str(parent)])
                sys.exit(0)

            # Create tool children for each tool call
            for tc in native_tool_calls:
                tool_json_str = json.dumps(tc)
                child_qno = subprocess.check_output([
                    sys.executable, 'jobber.py', 'create',
                    '--type', 'tool',
                    '--state', 'ready',
                    '--parent', str(qno),
                    '--tool-name', tc['function']['name'],
                    '--tool-json', tool_json_str
                ]).decode().strip()
                with open(os.path.join(job_folder, f'sub.{child_qno}'), 'w') as f:
                    pass
            move_job_folder(qno, 'processing', 'pending')
            print(f"Job {qno} pending – created {len(native_tool_calls)} tool child(ren)", file=sys.stderr)
        else:
            # No tool calls – done
            move_job_folder(qno, 'processing', 'done')
            print(f"Job {qno} completed", file=sys.stderr)
            parent = job.get('parent', 0)
            if parent:
                subprocess.run([sys.executable, 'jobber.py', 'cleanup', str(parent)])

    except Exception as e:
        print(f"Job {qno} failed: {e}", file=sys.stderr)
        move_job_folder(qno, 'processing', 'error')


def propagate_tool_result(tool_qno, parent_qno, tool_name, call_id):
    """Append the tool result message to the parent's conversation.json and re-enable it."""
    lf = acquire_lock()
    try:
        tool_folder = os.path.join(JOBS_DIR, 'processing', str(tool_qno))
        output_path = os.path.join(tool_folder, 'output.txt')
        if not os.path.exists(output_path):
            raise Exception(f"Tool output not found: {output_path}")
        with open(output_path) as f:
            tool_output = f.read().strip()

        # Find parent job (could be in ready, processing, or pending)
        parent_folder = None
        for pst in ['ready', 'processing', 'pending']:
            candidate = os.path.join(JOBS_DIR, pst, str(parent_qno))
            if os.path.exists(candidate):
                parent_folder = candidate
                break
        if not parent_folder:
            print(f"Parent job {parent_qno} not found for tool {tool_qno}", file=sys.stderr)
            return

        # Append tool result to conversation.json
        conv_path = os.path.join(parent_folder, 'conversation.json')
        if os.path.exists(conv_path):
            with open(conv_path) as f:
                conv = json.load(f)
        else:
            conv = []
        conv.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": tool_name,
            "content": tool_output
        })
        with open(conv_path, 'w') as f:
            json.dump(conv, f, indent=2)

        # Remove sub marker
        sub_file = os.path.join(parent_folder, f'sub.{tool_qno}')
        if os.path.exists(sub_file):
            os.remove(sub_file)
        # If no more sub files, move parent to ready
        remaining = [f for f in os.listdir(parent_folder) if f.startswith('sub.')]
        if not remaining:
            current_state = None
            for st in ['pending', 'processing', 'ready']:
                if os.path.exists(os.path.join(JOBS_DIR, st, str(parent_qno))):
                    current_state = st
                    break
            if current_state:
                move_job_folder(parent_qno, current_state, 'ready')
                print(f"Job {parent_qno} ready again (tool {tool_qno} finished)", file=sys.stderr)
    finally:
        release_lock(lf)


if __name__ == '__main__':
    main()
