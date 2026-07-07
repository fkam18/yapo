#!/usr/bin/env python3
"""
Init – create a new Yapo job.
Usage: init.py "your prompt" [--mtype <model_type>] [--name "job name"] [--start-after HH:MM] [--max-duration <seconds>] [--rag <tool>:<query> ...]
"""

import sys, subprocess, json, argparse
from config import load_config

def main():
    # Load config to get available model types
    config = load_config()
    model_types = sorted(set(
        m['type'] for m in config.get('models', [])
        if m.get('server') != 'nuc' and m.get('type') not in ('embed', 'summarise', 'router')
    ))

    parser = argparse.ArgumentParser()
    parser.add_argument('prompt', nargs='?', help='The user prompt (or pipe from stdin)')
    parser.add_argument('--rag', action='append', default=[])
    parser.add_argument('--mtype', choices=model_types,
                        help=f'Force a specific model type, skip routing. Available: {", ".join(model_types)}')
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

    # If model type is given, pass it directly to jobber
    # The runner will resolve model_type → server model name later
    model_type = args.mtype if args.mtype else ''

    # Create main job (pending if RAG, otherwise ready)
    state = 'pending' if args.rag else 'ready'
    create_cmd = [
        'python3', 'jobber.py', 'create',
        '--type', 'main',
        '--state', state,
        '--model-type', model_type,
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
