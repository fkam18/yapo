#!/usr/bin/env python3
"""
Yapo – main scheduler loop with GPU energy management.
"""

import os, sys, time, subprocess, json, signal, socket, struct
from datetime import datetime, timezone
from jobber import list_jobs, move_job_folder, acquire_lock, release_lock
from config import load_config, get_server, get_tool

# ---------- capacity tracker ----------
server_capacity = {}
tool_capacity = {}

# ---------- energy management state ----------
# Per server: True if Yapo woke this GPU, else False
gpu_woken_by_yapo = {}
# Timestamp of the last job completion for each GPU server
last_gpu_job_end = {}

def update_capacity(config):
    global server_capacity, tool_capacity
    for srv in config.get('servers', []):
        if srv.get('schedulable', False):
            server_capacity[srv['name']] = 0
    for tool in config.get('tools', []):
        tool_capacity[tool['name']] = 0

def can_launch(job, config):
    if job['type'] == 'main':
        model_name = job.get('model', '')
        if not model_name:
            return True   # unrouted, let runner handle
        model_cfg = None
        for m in config.get('models', []):
            if m['name'] == model_name:
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

# ---------- GPU energy management ----------

def server_reachable(server):
    """Check if Ollama on the given server is responding."""
    import urllib.request, urllib.error
    try:
        url = f"{server['url']}/api/tags"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False

def send_wol(mac_address):
    """Send a Wake‑on‑LAN magic packet to the given MAC address."""
    # Convert MAC to bytes
    mac_bytes = bytes.fromhex(mac_address.replace(':', '').replace('-', ''))
    if len(mac_bytes) != 6:
        raise ValueError("Invalid MAC address")
    magic = b'\xff' * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(magic, ('<broadcast>', 9))

def is_within_schedule(schedule):
    """Check if current time falls within any configured window."""
    now = datetime.now(timezone.utc)
    for window in schedule.get('windows', []):
        start = window['start']
        end = window['end']
        # Convert HH:MM to today's datetime
        today = now.date()
        start_dt = datetime.strptime(start, '%H:%M').replace(year=today.year, month=today.month, day=today.day, tzinfo=now.tzinfo)
        end_dt = datetime.strptime(end, '%H:%M').replace(year=today.year, month=today.month, day=today.day, tzinfo=now.tzinfo)
        if end_dt <= start_dt:   # overnight window
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

    # Initialise energy state for each GPU server
    for srv in config.get('servers', []):
        if srv.get('schedulable') and srv.get('mac_address'):
            gpu_woken_by_yapo[srv['name']] = False
            last_gpu_job_end[srv['name']] = None

    gpu_schedule = config.get('gpu_schedule', {})
    on_demand = gpu_schedule.get('on_demand', False)
    idle_timeout = gpu_schedule.get('idle_timeout_seconds', 180)

    print("Yapo scheduler started.", file=sys.stderr)

    while True:
        # ---- check ready queue ----
        lf = acquire_lock()
        try:
            ready_jobs = list_jobs('ready')
        finally:
            release_lock(lf)

        ready_jobs.sort(key=lambda x: x['qno'])

        for job in ready_jobs:
            if not can_launch(job, config):
                continue

            # Determine which server this job needs (if any)
            required_server = None
            if job['type'] == 'main' and job.get('model'):
                for m in config.get('models', []):
                    if m['name'] == job['model']:
                        required_server = m['server']
                        break
            # Tool jobs may run on NUC (no GPU), ignore energy for those

            if required_server:
                srv = get_server(required_server)
                if srv and srv.get('schedulable') and srv.get('mac_address'):
                    # Check if GPU is reachable
                    reachable = server_reachable(srv)
                    if not reachable:
                        # Should we wake it?
                        should_wake = False
                        if on_demand:
                            should_wake = True
                        else:
                            # Scheduled mode: only wake if within a window
                            if is_within_schedule(gpu_schedule):
                                should_wake = True
                        if should_wake:
                            print(f"Waking GPU server {required_server} via WoL...", file=sys.stderr)
                            send_wol(srv['mac_address'])
                            time.sleep(10)   # allow boot
                            reachable = server_reachable(srv)
                            if not reachable:
                                print(f"GPU {required_server} still unreachable, skipping job", file=sys.stderr)
                                continue
                            gpu_woken_by_yapo[required_server] = True
                        else:
                            print(f"GPU {required_server} not reachable and not in schedule, skipping job", file=sys.stderr)
                            continue
                    else:
                        # Server was already up – we did NOT wake it
                        gpu_woken_by_yapo[required_server] = False

            print(f"Launching job {job['qno']} (type={job['type']})", file=sys.stderr)
            pid = launch_job(job['qno'], config)
            if job['type'] == 'main':
                model_name = job.get('model', '')
                if model_name:
                    for m in config.get('models', []):
                        if m['name'] == model_name:
                            server_name = m['server']
                            server_capacity[server_name] += 1
                            break
            elif job['type'] == 'tool':
                tool_name = job.get('tool_name', '')
                tool_capacity[tool_name] = tool_capacity.get(tool_name, 0) + 1

        time.sleep(3)

        # ---- reap children ----
        try:
            while True:
                wpid, status = os.waitpid(-1, os.WNOHANG)
                if wpid == 0:
                    break
        except ChildProcessError:
            pass

        # ---- recalculate capacity and check idle timeout ----
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
            if job['type'] == 'main':
                model_name = job.get('model', '')
                if model_name:
                    for m in config.get('models', []):
                        if m['name'] == model_name:
                            server_name = m['server']
                            server_capacity[server_name] = server_capacity.get(server_name, 0) + 1
                            break
            elif job['type'] == 'tool':
                tool_name = job.get('tool_name', '')
                tool_capacity[tool_name] = tool_capacity.get(tool_name, 0) + 1

        # ---- GPU idle / suspend logic ----
        now = datetime.now(timezone.utc)
        for srv in config.get('servers', []):
            if not srv.get('schedulable') or not srv.get('mac_address'):
                continue
            server_name = srv['name']
            # Only consider if we have capacity info
            active_jobs = server_capacity.get(server_name, 0)
            if active_jobs == 0:
                # No running GPU jobs – update last idle timestamp if not set
                if last_gpu_job_end[server_name] is None:
                    last_gpu_job_end[server_name] = now
                else:
                    idle_seconds = (now - last_gpu_job_end[server_name]).total_seconds()
                    if idle_seconds >= idle_timeout:
                        if gpu_woken_by_yapo.get(server_name, False):
                            # Yapo woke this server, so we should suspend it
                            # But only if we are allowed: in on_demand mode, always; in scheduled mode, only if outside window
                            should_suspend = False
                            if on_demand:
                                should_suspend = True
                            else:
                                if not is_within_schedule(gpu_schedule):
                                    should_suspend = True
                            if should_suspend:
                                cmd = srv.get('suspend_command')
                                if cmd:
                                    print(f"Suspending GPU {server_name} after idle timeout...", file=sys.stderr)
                                    subprocess.run(cmd, shell=True)
                                    # Reset state
                                    gpu_woken_by_yapo[server_name] = False
                                    last_gpu_job_end[server_name] = None
            else:
                # There are active jobs, so reset idle timer
                last_gpu_job_end[server_name] = None

if __name__ == '__main__':
    main()
