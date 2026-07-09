#!/usr/bin/env python3
"""
Jobber – serialised CRUD for jobs.
Usage:
  jobber create --type <type> [--state <state>] [--parent <qno>] [--model-type <model type>] [--prompt-file <file>] [--tool-json '<json>'] [--job-name <name>] [--start-after HH:MM] [--max-job-duration <seconds>]
  jobber move <qno> <new_state>
  jobber append <qno> <file> <text>
  jobber clone <qno> --new-jobid <id>
  jobber cleanup <qno>
"""

import os, sys, shutil, json, uuid, time, argparse, fcntl, base64

from config import get_yapo_root

YAPO_ROOT = get_yapo_root()
JOBS_DIR = os.path.join(YAPO_ROOT, 'jobs')
LOCK_FILE = os.path.join(YAPO_ROOT, 'jobber.lock')

# Named pipe for SSE event signalling
SIGNAL_PIPE = os.path.join(YAPO_ROOT, 'event.pipe')

def acquire_lock():
    """Acquire exclusive lock."""
    os.makedirs(JOBS_DIR, exist_ok=True)
    lf = open(LOCK_FILE, 'w')
    fcntl.flock(lf, fcntl.LOCK_EX)
    return lf

def release_lock(lf):
    fcntl.flock(lf, fcntl.LOCK_UN)
    lf.close()

def read_job_toml(qno):
    """Return dict from job.toml or None."""
    toml_file = os.path.join(JOBS_DIR, 'processing', str(qno), 'job.toml')
    for state in ['ready', 'processing', 'pending', 'done', 'error']:
        path = os.path.join(JOBS_DIR, state, str(qno), 'job.toml')
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    return None

def write_job_toml(qno, state, data):
    folder = os.path.join(JOBS_DIR, state, str(qno))
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'job.toml'), 'w') as f:
        json.dump(data, f)

def move_job_folder(qno, from_state, to_state):
    src = os.path.join(JOBS_DIR, from_state, str(qno))
    dst = os.path.join(JOBS_DIR, to_state, str(qno))
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        # Signal SSE clients
        try:
            fd = os.open(SIGNAL_PIPE, os.O_WRONLY | os.O_NONBLOCK)
            os.write(fd, b'x')
            os.close(fd)
        except:
            pass
        return True
    return False

def get_next_qno():
    """Find the next queue number (largest + 1)."""
    max_q = 0
    for state in ['ready', 'processing', 'pending', 'done', 'error']:
        state_dir = os.path.join(JOBS_DIR, state)
        if os.path.exists(state_dir):
            for name in os.listdir(state_dir):
                if name.isdigit():
                    q = int(name)
                    if q > max_q:
                        max_q = q
    return max_q + 1


def create_job(type, state='ready', model_type='', parent=0, prompt_text='',
               job_name='', start_after=None, max_job_duration=None,
               attachments=None, tool_name=None, tool_json=None):
    """
    Create a job folder. Called by both CLI and Python API.
    
    Args:
        attachments: list of dicts with keys 'filename', 'content' (base64), 'mime'
    
    Returns:
        int: the new queue number
    """
    if attachments is None:
        attachments = []

    lf = acquire_lock()
    try:
        qno = get_next_qno()
        folder = os.path.join(JOBS_DIR, state, str(qno))
        os.makedirs(folder, exist_ok=True)

        # job.toml
        job_data = {
            'job_id': uuid.uuid4().hex[:12],
            'type': type,
            'model_type': model_type or '',
            'parent': parent or 0,
            'name': job_name or '',
            'start_after': start_after,
            'max_job_duration': max_job_duration,
            'fail_on_child_error': False,
            'compact': False
        }
        if type == 'tool':
            job_data['tool_name'] = tool_name or ''
        with open(os.path.join(folder, 'job.toml'), 'w') as f:
            json.dump(job_data, f)

        # parent file
        if parent:
            with open(os.path.join(folder, f'parent.{parent}'), 'w') as f:
                pass

        # prompt.txt
        if prompt_text:
            with open(os.path.join(folder, 'prompt.txt'), 'w') as f:
                f.write(prompt_text)

        # tool_call.json
        if tool_json:
            with open(os.path.join(folder, 'tool_call.json'), 'w') as f:
                f.write(tool_json)

        # attachments
        if attachments:
            assets_dir = os.path.join(folder, 'assets')
            os.makedirs(assets_dir, exist_ok=True)
            for att in attachments:
                filename = att.get('filename', 'untitled')
                content_b64 = att.get('content', '')
                if content_b64:
                    try:
                        file_content = base64.b64decode(content_b64)
                        with open(os.path.join(assets_dir, filename), 'wb') as f:
                            f.write(file_content)
                    except Exception as e:
                        print(f"Warning: failed to save attachment {filename}: {e}", file=sys.stderr)
        # Signal SSE clients
        try:
            fd = os.open(SIGNAL_PIPE, os.O_WRONLY | os.O_NONBLOCK)
            os.write(fd, b'x')
            os.close(fd)
        except:
            pass

        print(qno)
        return qno
    finally:
        release_lock(lf)


def create_job_cli(args):
    """CLI wrapper for create_job."""
    start_after = None
    if hasattr(args, 'start_after') and args.start_after:
        start_after = args.start_after.strip()

    max_job_duration = None
    if hasattr(args, 'max_job_duration') and args.max_job_duration:
        try:
            max_job_duration = int(args.max_job_duration)
        except ValueError:
            print(f"Invalid max-job-duration: {args.max_job_duration}", file=sys.stderr)
            sys.exit(1)

    prompt_text = ''
    if args.prompt_file:
        with open(args.prompt_file) as f:
            prompt_text = f.read()

    create_job(
        type=args.type,
        state=args.state if args.state else 'ready',
        model_type=getattr(args, 'model_type', '') or '',
        parent=args.parent if args.parent else 0,
        prompt_text=prompt_text,
        job_name=getattr(args, 'job_name', '') or '',
        start_after=start_after,
        max_job_duration=max_job_duration,
        tool_name=getattr(args, 'tool_name', None),
        tool_json=getattr(args, 'tool_json', None),
    )


def move_job(args):
    lf = acquire_lock()
    try:
        qno = args.qno
        current_state = None
        for state in ['ready', 'processing', 'pending', 'done', 'error']:
            if os.path.exists(os.path.join(JOBS_DIR, state, str(qno))):
                current_state = state
                break
        if current_state is None:
            print(f"Job {qno} not found", file=sys.stderr)
            sys.exit(1)
        move_job_folder(qno, current_state, args.new_state)
    finally:
        release_lock(lf)


def append_text(args):
    lf = acquire_lock()
    try:
        for state in ['ready', 'processing', 'pending']:
            folder = os.path.join(JOBS_DIR, state, str(args.qno))
            if os.path.exists(folder):
                filepath = os.path.join(folder, args.file)
                with open(filepath, 'a') as f:
                    f.write(args.text + '\n')
                break
    finally:
        release_lock(lf)


def clone_job(args):
    lf = acquire_lock()
    try:
        src_qno = args.qno
        new_id = args.new_jobid
        for state in ['ready', 'processing', 'pending']:
            src_folder = os.path.join(JOBS_DIR, state, str(src_qno))
            if os.path.exists(src_folder):
                dst_folder = os.path.join(JOBS_DIR, 'ready', str(new_id))
                shutil.copytree(src_folder, dst_folder)
                toml_path = os.path.join(dst_folder, 'job.toml')
                with open(toml_path) as f:
                    data = json.load(f)
                data['compact'] = True
                data['job_id'] = new_id
                with open(toml_path, 'w') as f:
                    json.dump(data, f)
                break
    finally:
        release_lock(lf)


def cleanup_job(args):
    lf = acquire_lock()
    try:
        qno = args.qno
        for state in ['pending', 'processing']:
            folder = os.path.join(JOBS_DIR, state, str(qno))
            if os.path.exists(folder):
                with open(os.path.join(folder, 'job.toml')) as f:
                    job_data = json.load(f)
                job_type = job_data.get('type', '')
                output_path = os.path.join(folder, 'output.txt')

                if job_type == 'tool' and os.path.exists(output_path):
                    move_job_folder(qno, state, 'done')
                    done_folder = os.path.join(JOBS_DIR, 'done', str(qno))
                    parent_files = [f for f in os.listdir(done_folder) if f.startswith('parent.')]
                    if parent_files:
                        parent_qno = int(parent_files[0].split('.')[1])
                        with open(output_path) as f:
                            tool_output = f.read()
                        for pst in ['ready', 'processing', 'pending']:
                            parent_path = os.path.join(JOBS_DIR, pst, str(parent_qno))
                            if os.path.exists(parent_path):
                                ctx_path = os.path.join(parent_path, 'context.txt')
                                with open(ctx_path, 'a') as apf:
                                    apf.write(tool_output + '\n')
                                sub_file = os.path.join(parent_path, f'sub.{qno}')
                                if os.path.exists(sub_file):
                                    os.remove(sub_file)
                                remaining = [f for f in os.listdir(parent_path) if f.startswith('sub.')]
                                if not remaining:
                                    move_job_folder(parent_qno, pst, 'ready')
                                break
                    return

                sub_files = [f for f in os.listdir(folder) if f.startswith('sub.')]
                if not sub_files:
                    if os.path.exists(output_path):
                        with open(output_path) as f:
                            out = f.read().strip()
                        try:
                            outj = json.loads(out)
                            if 'done' in outj:
                                move_job_folder(qno, state, 'done')
                                parent_files = [f for f in os.listdir(os.path.join(JOBS_DIR, 'done', str(qno))) if f.startswith('parent.')]
                                if parent_files:
                                    parent_qno = int(parent_files[0].split('.')[1])
                                    ctx_path = os.path.join(os.path.join(JOBS_DIR, 'done', str(qno)), 'context.txt')
                                    if os.path.exists(ctx_path):
                                        with open(ctx_path) as cf:
                                            ctx_text = cf.read()
                                        for pst in ['ready', 'processing', 'pending']:
                                            pf = os.path.join(JOBS_DIR, pst, str(parent_qno))
                                            if os.path.exists(pf):
                                                with open(os.path.join(pf, 'context.txt'), 'a') as apf:
                                                    apf.write(ctx_text + '\n')
                                                sub_file = os.path.join(pf, f'sub.{qno}')
                                                if os.path.exists(sub_file):
                                                    os.remove(sub_file)
                                                remaining = [f for f in os.listdir(pf) if f.startswith('sub.')]
                                                if not remaining:
                                                    move_job_folder(parent_qno, pst, 'ready')
                                                break
                        except json.JSONDecodeError:
                            pass
                break
    finally:
        release_lock(lf)


def list_jobs(state):
    """Return list of job dicts for given state."""
    jobs = []
    state_dir = os.path.join(JOBS_DIR, state)
    if os.path.exists(state_dir):
        for name in os.listdir(state_dir):
            if name.isdigit():
                qno = int(name)
                toml = os.path.join(state_dir, name, 'job.toml')
                if os.path.exists(toml):
                    with open(toml) as f:
                        data = json.load(f)
                    data['qno'] = qno
                    jobs.append(data)
    return jobs


# CLI
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd')

    create_parser = sub.add_parser('create')
    create_parser.add_argument('--type', required=True)
    create_parser.add_argument('--state', default='ready')
    create_parser.add_argument('--parent', type=int, default=0)
    create_parser.add_argument('--model-type', default='')
    create_parser.add_argument('--prompt-file', default=None)
    create_parser.add_argument('--tool-json', default=None)
    create_parser.add_argument('--tool-name', default=None)
    create_parser.add_argument('--job-name', default='', help='Human‑readable job name')
    create_parser.add_argument('--start-after', default='', help='Start time in HH:MM format (e.g. 22:00)')
    create_parser.add_argument('--max-job-duration', type=int, default=None, help='Max job duration in seconds (overrides global default)')

    move_parser = sub.add_parser('move')
    move_parser.add_argument('qno', type=int)
    move_parser.add_argument('new_state')

    append_parser = sub.add_parser('append')
    append_parser.add_argument('qno', type=int)
    append_parser.add_argument('file')
    append_parser.add_argument('text')

    clone_parser = sub.add_parser('clone')
    clone_parser.add_argument('qno', type=int)
    clone_parser.add_argument('--new-jobid', required=True)

    cleanup_parser = sub.add_parser('cleanup')
    cleanup_parser.add_argument('qno', type=int)

    args = parser.parse_args()

    if args.cmd == 'create':
        create_job_cli(args)
    elif args.cmd == 'move':
        move_job(args)
    elif args.cmd == 'append':
        append_text(args)
    elif args.cmd == 'clone':
        clone_job(args)
    elif args.cmd == 'cleanup':
        cleanup_job(args)
    else:
        parser.print_help()
