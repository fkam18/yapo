#!/usr/bin/env python3
"""
Init – create a new Yapo job.
Usage: init.py "your prompt" [--mtype code|others|visual] [--name "job name"] [--start-after HH:MM] [--max-duration <seconds>] [--rag <tool>:<query> ...]
"""

import sys, subprocess, json, argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('prompt', nargs='?', help='The user prompt (or pipe from stdin)')
    parser.add_argument('--rag', action='append', default=[])
    parser.add_argument('--mtype', choices=['code', 'others', 'visual'],
                        help='Force a specific model type, skip routing')
    parser.add_argument('--name', '-n', type=str, default='',
                        help='Human‑readable name for the job (displayed in dashboard)')
    parser.add_argument('--start-after', type=str, default='',
                        help='Start time in HH:MM format (e.g. 22:00). Job will not run before this time.')
    parser.add_argument('--max-duration', type=int, default=None,
                        help='Max job duration in seconds. Overrides the global max_job_duration.')
    args = parser.parse_args()

    if args.prompt:
        prompt_text = args.prompt
    elif not sys.stdin.isatty():
        prompt_text = sys.stdin.read().strip()
    else:
        print("Error: no prompt provided", file=sys.stderr)
        sys.exit(1)

    # Write prompt to temp file
    with open('/tmp/yapo_prompt.txt', 'w') as f:
        f.write(prompt_text)

    # If model type is given, look up the model name from config and pass it to jobber
    model_name = ''
    if args.mtype:
        from config import load_config
        config = load_config()
        for m in config.get('models', []):
            if m.get('type') == args.mtype and m.get('server') != 'nuc':
                model_name = m['name']
                break
        if not model_name:
            print(f"Error: no model found for type '{args.mtype}'", file=sys.stderr)
            sys.exit(1)

    # Create main job (pending if RAG, otherwise ready)
    state = 'pending' if args.rag else 'ready'
    create_cmd = [
        'python3', 'jobber.py', 'create',
        '--type', 'main',
        '--state', state,
        '--model', model_name,
        '--prompt-file', '/tmp/yapo_prompt.txt',
        '--job-name', args.name
    ]
    if args.start_after:
        create_cmd.extend(['--start-after', args.start_after])
    if args.max_duration is not None:
        create_cmd.extend(['--max-job-duration', str(args.max_duration)])

    qno = subprocess.check_output(create_cmd).decode().strip()
    print(f"Job {qno} created.", file=sys.stderr)

    if args.rag:
        main_qno = qno
        for rag_spec in args.rag:
            tool_name, query = rag_spec.split(':', 1)
            tool_json = json.dumps({"tool": tool_name, "arguments": {"query": query}})
            sub_qno = subprocess.check_output([
                'python3', 'jobber.py', 'create',
                '--type', 'tool',
                '--state', 'pending',
                '--parent', main_qno,
                '--tool-name', tool_name,
                '--tool-json', tool_json
            ]).decode().strip()
            subprocess.run(['python3', 'jobber.py', 'move', sub_qno.strip(), 'ready'])
        subprocess.run(['python3', 'jobber.py', 'move', main_qno, 'ready'])

if __name__ == '__main__':
    main()
