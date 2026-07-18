#!/usr/bin/env python3
"""
Yapo – main scheduler loop with GPU energy management (refactored).
"""

import os, sys, time, subprocess, json, signal, socket, struct
from datetime import datetime, timezone
from jobber import list_jobs, move_job_folder, acquire_lock, release_lock
from config import load_config, get_server, get_tool, get_yapo_root, get_max_job_duration
YAPO_ROOT = get_yapo_root()

import sys
from datetime import datetime
from log import log_write

class LogStderr:
    def __init__(self):
        self.buffer = ''
    def write(self, data):
        self.buffer += data
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if line.strip():
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                log_write(f"yapo {ts}: {line}")
    def flush(self):
        if self.buffer.strip():
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_write(f"yapo {ts}: {self.buffer}")
            self.buffer = ''

sys.stderr = LogStderr()

def reload_config_signal(signum, frame):
    """Reload config on SIGHUP."""
    global _config
    from config import load_config
    _config = None
    load_config()
    print("Config reloaded via SIGHUP", file=sys.stderr)

signal.signal(signal.SIGHUP, reload_config_signal)

# ---------- capacity tracker ----------
server_capacity = {}
tool_capacity = {}

# ---------- energy management state ----------
gpu_woken_by_yapo = {}
last_gpu_job_end = {}

# ──────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────

def update_capacity(config):
    global server_capacity, tool_capacity
    for srv in config.get('servers', []):
        if srv.get('schedulable', False):
            server_capacity[srv['name']] = 0
    for tool in config.get('tools', []):
        tool_capacity[tool['name']] = 0


def time_str_to_today(time_str: str):
    now = datetime.now()
    try:
        h, m = map(int, time_str.split(':'))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)
    except (ValueError, AttributeError):
        return None


def route_job(job, config):
    """Call the MCP router to classify an unrouted job.  Updates job dict in place.
    Returns True on success, False on failure."""
    route_tool = get_tool('route_prompt')
    if not route_tool:
        print("route_prompt tool not found – cannot route job", file=sys.stderr)
        return False

    qno = job['qno']
    prompt_path = os.path.join(YAPO_ROOT, 'jobs', 'ready', str(qno), 'prompt.txt')
    if os.path.exists(prompt_path):
        with open(prompt_path) as f:
            prompt_text = f.read().strip()
    else:
        prompt_text = job.get('prompt', '')

    try:
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), 'yapo_mcp.py')],
            input=json.dumps({"tool": "route_prompt", "arguments": {"prompt": prompt_text}}),
            capture_output=True, text=True, timeout=30
        )
        model_type = result.stdout.strip().lower()
        if model_type in ['code', 'others', 'visual']:
            job['model_type'] = model_type
            # Persist to job.toml
            job_path = os.path.join(YAPO_ROOT, 'jobs', 'ready', str(qno), 'job.toml')
            with open(job_path, 'w') as f:
                json.dump(job, f)
            print(f"Job {qno} pre-routed to type={model_type}", file=sys.stderr)
            return True
        else:
            print(f"Job {qno} routing returned invalid type: {model_type}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"Job {qno} routing failed: {e}", file=sys.stderr)
        return False


def resolve_server_for_job(job, config):
    """Return (server_name, server_dict) for the job's model_type, or (None, None)."""
    model_type = job.get('model_type', '')
    if not model_type:
        return None, None
    for m in config.get('models', []):
        if m.get('type') == model_type:
            server_name = m['server']
            return server_name, get_server(server_name)
    return None, None


def server_reachable(server):
    import importlib, socket
    backend_name = server.get("backend", "openai")
    module_name = f"conn_{backend_name}"
    try:
        conn = importlib.import_module(module_name)
        if hasattr(conn, 'server_reachable'):
            return conn.server_reachable(server)
    except ImportError:
        pass
    url = server['url']
    host = url.split("://")[-1].split(":")[0]
    try:
        port = int(url.split(":")[-1])
    except (ValueError, IndexError):
        port = 80
    try:
        with socket.create_connection((host, port), timeout=5):
            return True
    except Exception:
        return False


def send_wol(mac_address):
    mac_bytes = bytes.fromhex(mac_address.replace(':', '').replace('-', ''))
    if len(mac_bytes) != 6:
        raise ValueError("Invalid MAC address")
    magic = b'\xff' * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(magic, ('<broadcast>', 9))


def is_within_schedule(schedule):
    if not schedule:
        return False
    now = datetime.now()
    for window in schedule.get('windows', []):
        start = window['start']
        end = window['end']
        today = now.date()
        start_dt = datetime.strptime(start, '%H:%M').replace(year=today.year, month=today.month, day=today.day)
        end_dt = datetime.strptime(end, '%H:%M').replace(year=today.year, month=today.month, day=today.day)
        if end_dt <= start_dt:
            if now >= start_dt or now <= end_dt:
                return True
        else:
            if start_dt <= now <= end_dt:
                return True
    return False


def should_wake_gpu(srv):
    """Decide whether the GPU should be woken based on schedule or on_demand."""
    schedule = srv.get('gpu_schedule', {})
    if schedule.get('on_demand', False):
        return True
    return is_within_schedule(schedule)


def ensure_gpu_ready(srv, server_name):
    """Ensure the GPU is reachable.  Sends WoL if needed and waits for boot.
    Returns True if the GPU is reachable, False if it could not be woken."""
    if server_reachable(srv):
        gpu_woken_by_yapo[server_name] = False
        return True

    if not should_wake_gpu(srv):
        print(f"GPU {server_name} not in schedule / on_demand – skipping", file=sys.stderr)
        return False

    print(f"Waking GPU {server_name} via WoL...", file=sys.stderr)
    send_wol(srv['mac_address'])
    gpu_woken_by_yapo[server_name] = True

    # Wait for GPU to boot (up to 120 seconds)
    for attempt in range(1, 13):   # 12 attempts × 10s = 2 minutes
        time.sleep(10)
        if server_reachable(srv):
            print(f"GPU {server_name} reachable after {attempt * 10}s", file=sys.stderr)
            return True
        print(f"GPU {server_name} still booting (attempt {attempt}/12)...", file=sys.stderr)

    print(f"GPU {server_name} did not become reachable", file=sys.stderr)
    return False


def maybe_suspend_gpu(srv, server_name, now):
    """Suspend the GPU if it has been idle long enough and Yapo woke it."""
    # Don't try to suspend if GPU is already unreachable
    if not server_reachable(srv):
        return
    schedule = srv.get('gpu_schedule', {})
    idle_timeout = schedule.get('idle_timeout_seconds', 180)

    if server_capacity.get(server_name, 0) > 0:
        last_gpu_job_end[server_name] = None
        return

    if last_gpu_job_end[server_name] is None:
        last_gpu_job_end[server_name] = now
        return

    idle_seconds = (now - last_gpu_job_end[server_name]).total_seconds()
    if idle_seconds < idle_timeout:
        return

    # Only suspend if Yapo originally woke the GPU, or if on_demand is set
    if not gpu_woken_by_yapo.get(server_name, False) and not schedule.get('on_demand', False):
        return

    cmd = srv.get('suspend_command')
    if not cmd:
        return

    print(f"Suspending GPU {server_name} after idle timeout ({idle_seconds:.0f}s)...", file=sys.stderr)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Suspend command failed: {result.stderr}", file=sys.stderr)
    else:
        print(f"Suspend command succeeded.", file=sys.stderr)
        gpu_woken_by_yapo[server_name] = False
        last_gpu_job_end[server_name] = None


def can_launch(job, config):
    """Check if the job can be launched given current capacities and time constraints."""
    if job['type'] == 'main':
        model_type = job.get('model_type', '')
        if not model_type:
            return True   # still unrouted – let caller handle

        start_after = job.get('start_after', '')
        if start_after:
            target_time = time_str_to_today(start_after)
            if target_time and datetime.now() < target_time:
                return False

        _, srv = resolve_server_for_job(job, config)
        if not srv or not srv.get('schedulable', False):
            return False

        server_name = srv['name']
        if server_capacity.get(server_name, 0) >= srv.get('max_jobs', 1):
            return False

    elif job['type'] == 'tool':
        tool_name = job.get('tool_name', '')
        tool = get_tool(tool_name)
        if not tool:
            return False
        if tool_capacity.get(tool_name, 0) >= tool.get('concurrent_calls', 1):
            return False

    return True


def launch_job(qno, config):
    move_job_folder(qno, 'ready', 'processing')
    pid = os.fork()
    if pid == 0:
        os.execv(sys.executable, [sys.executable, 'runner.py', str(qno)])
    else:
        return pid


def update_processing_capacities(config):
    """Re‑compute server and tool capacities from jobs currently in processing."""
    for srv in server_capacity:
        server_capacity[srv] = 0
    for t in tool_capacity:
        tool_capacity[t] = 0

    lf = acquire_lock()
    try:
        processing = list_jobs('processing')
    finally:
        release_lock(lf)

    for job in processing:
        # Enforce max duration
        max_dur = job.get('max_job_duration') or get_max_job_duration()
        if max_dur:
            job_folder = os.path.join(YAPO_ROOT, 'jobs', 'processing', str(job['qno']))
            if os.path.exists(job_folder):
                created = os.path.getctime(job_folder)
                if time.time() - created > max_dur:
                    print(f"Job {job['qno']} exceeded max duration ({max_dur}s), moving to error", file=sys.stderr)
                    move_job_folder(job['qno'], 'processing', 'error')
                    continue

        if job['type'] == 'main':
            model_type = job.get('model_type', '')
            if model_type:
                for m in config.get('models', []):
                    if m.get('type') == model_type:
                        sn = m['server']
                        server_capacity[sn] = server_capacity.get(sn, 0) + 1
                        break
        elif job['type'] == 'tool':
            tool_name = job.get('tool_name', '')
            tool_capacity[tool_name] = tool_capacity.get(tool_name, 0) + 1


def main():
    config = load_config()
    update_capacity(config)
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)

    for srv in config.get('servers', []):
        if srv.get('schedulable') and srv.get('mac_address'):
            gpu_woken_by_yapo[srv['name']] = False
            last_gpu_job_end[srv['name']] = None

    print("Yapo scheduler started.", file=sys.stderr)

    while True:
        lf = acquire_lock()
        try:
            ready_jobs = list_jobs('ready')
        finally:
            release_lock(lf)

        ready_jobs.sort(key=lambda x: x['qno'])

        for job in ready_jobs:
            # ── 1. Route unrouted jobs ──
            if job['type'] == 'main' and not job.get('model_type', ''):
                if not route_job(job, config):
                    continue   # routing failed – skip this job for now

            # ── 2. Check basic constraints ──
            if not can_launch(job, config):
                continue

            # ── 3. Ensure GPU is ready (WoL if needed) ──
            server_name, srv = resolve_server_for_job(job, config)
            if srv and srv.get('schedulable') and srv.get('mac_address'):
                if not ensure_gpu_ready(srv, server_name):
                    continue   # GPU not reachable – leave in ready for next loop

            # ── 4. Launch the job ──
            print(f"Launching job {job['qno']} (type={job['type']})", file=sys.stderr)
            launch_job(job['qno'], config)

            if job['type'] == 'main':
                model_type = job.get('model_type', '')
                if model_type:
                    for m in config.get('models', []):
                        if m.get('type') == model_type:
                            server_capacity[m['server']] += 1
                            break
            elif job['type'] == 'tool':
                tool_name = job.get('tool_name', '')
                tool_capacity[tool_name] = tool_capacity.get(tool_name, 0) + 1

        time.sleep(3)

        # Reap finished children
        try:
            while True:
                wpid, status = os.waitpid(-1, os.WNOHANG)
                if wpid == 0:
                    break
        except ChildProcessError:
            pass

        # Update capacities and handle timeout
        update_processing_capacities(config)

        # GPU suspend check
        now = datetime.now()
        for srv in config.get('servers', []):
            if not srv.get('schedulable') or not srv.get('mac_address'):
                continue
            maybe_suspend_gpu(srv, srv['name'], now)


if __name__ == '__main__':
    main()
