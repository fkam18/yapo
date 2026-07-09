#!/usr/bin/env python3
"""
Yapo – main scheduler loop with GPU energy management.
"""

import os, sys, time, subprocess, json, signal, socket, struct
from datetime import datetime, timezone
from jobber import list_jobs, move_job_folder, acquire_lock, release_lock
from config import load_config, get_server, get_tool, get_yapo_root, get_max_job_duration
YAPO_ROOT = get_yapo_root()

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

def can_launch(job, config):
    if job['type'] == 'main':
        model_type = job.get('model_type', '')
        if not model_type:
            return True   # unrouted, let runner handle

        start_after = job.get('start_after', '')
        if start_after:
            target_time = time_str_to_today(start_after)
            if target_time and datetime.now() < target_time:
                return False

        model_cfg = None
        for m in config.get('models', []):
            if m.get('type') == model_type:
                model_cfg = m
                break
        if not model_cfg:
            return False
        server_name = model_cfg['server']
        srv = get_server(server_name)
        if not srv or not srv.get('schedulable'):
            return False
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
            if not can_launch(job, config):
                continue

            required_server = None
            if job['type'] == 'main' and job.get('model_type'):
                for m in config.get('models', []):
                    if m.get('type') == job['model_type']:
                        required_server = m['server']
                        break

            if required_server:
                srv = get_server(required_server)
                if srv and srv.get('schedulable') and srv.get('mac_address'):
                    server_schedule = srv.get('gpu_schedule', {})
                    on_demand = server_schedule.get('on_demand', False)
                    reachable = server_reachable(srv)
                    if not reachable:
                        should_wake = False
                        if on_demand:
                            should_wake = True
                        else:
                            if is_within_schedule(server_schedule):
                                should_wake = True
                        if should_wake:
                            print(f"Waking GPU server {required_server} via WoL...", file=sys.stderr)
                            send_wol(srv['mac_address'])
                            time.sleep(10)
                            reachable = server_reachable(srv)
                            if not reachable:
                                print(f"GPU {required_server} still unreachable, skipping job", file=sys.stderr)
                                continue
                            gpu_woken_by_yapo[required_server] = True
                        else:
                            print(f"GPU {required_server} not reachable and not in schedule, skipping job", file=sys.stderr)
                            continue
                    else:
                        gpu_woken_by_yapo[required_server] = False

            print(f"Launching job {job['qno']} (type={job['type']})", file=sys.stderr)
            pid = launch_job(job['qno'], config)
            if job['type'] == 'main':
                model_type = job.get('model_type', '')
                if model_type:
                    for m in config.get('models', []):
                        if m.get('type') == model_type:
                            server_name = m['server']
                            server_capacity[server_name] += 1
                            break
            elif job['type'] == 'tool':
                tool_name = job.get('tool_name', '')
                tool_capacity[tool_name] = tool_capacity.get(tool_name, 0) + 1

        time.sleep(3)

        try:
            while True:
                wpid, status = os.waitpid(-1, os.WNOHANG)
                if wpid == 0:
                    break
        except ChildProcessError:
            pass

        lf = acquire_lock()
        try:
            processing = list_jobs('processing')
        finally:
            release_lock(lf)

        for srv in server_capacity:
            server_capacity[srv] = 0
        for t in tool_capacity:
            tool_capacity[t] = 0
        for job in processing:
            max_dur = job.get('max_job_duration') or get_max_job_duration()
            if max_dur:
                job_folder = os.path.join(YAPO_ROOT, 'jobs', 'processing', str(job['qno']))
                if os.path.exists(job_folder):
                    created = os.path.getctime(job_folder)
                    elapsed = time.time() - created
                    if elapsed > max_dur:
                        print(f"Job {job['qno']} exceeded max duration ({max_dur}s), moving to error", file=sys.stderr)
                        move_job_folder(job['qno'], 'processing', 'error')
                        continue

            if job['type'] == 'main':
                model_type = job.get('model_type', '')
                if model_type:
                    for m in config.get('models', []):
                        if m.get('type') == model_type:
                            server_name = m['server']
                            server_capacity[server_name] = server_capacity.get(server_name, 0) + 1
                            break
            elif job['type'] == 'tool':
                tool_name = job.get('tool_name', '')
                tool_capacity[tool_name] = tool_capacity.get(tool_name, 0) + 1

        now = datetime.now()
        for srv in config.get('servers', []):
            if not srv.get('schedulable') or not srv.get('mac_address'):
                continue
            server_name = srv['name']
            server_schedule = srv.get('gpu_schedule', {})
            on_demand = server_schedule.get('on_demand', False)
            idle_timeout = server_schedule.get('idle_timeout_seconds', 180)

            active_jobs = server_capacity.get(server_name, 0)
            if active_jobs == 0:
                if last_gpu_job_end[server_name] is None:
                    last_gpu_job_end[server_name] = now
                else:
                    idle_seconds = (now - last_gpu_job_end[server_name]).total_seconds()
                    if idle_seconds >= idle_timeout:
                        if gpu_woken_by_yapo.get(server_name, False):
                            should_suspend = False
                            if on_demand:
                                should_suspend = True
                            else:
                                if not is_within_schedule(server_schedule):
                                    should_suspend = True
                            if should_suspend:
                                cmd = srv.get('suspend_command')
                                if cmd:
                                    print(f"Suspending GPU {server_name} after idle timeout...", file=sys.stderr)
                                    subprocess.run(cmd, shell=True)
                                    gpu_woken_by_yapo[server_name] = False
                                    last_gpu_job_end[server_name] = None
            else:
                last_gpu_job_end[server_name] = None

if __name__ == '__main__':
    main()
