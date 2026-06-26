#!/usr/bin/env python3
"""
catjob.py – Print job details and output for a given queue number.
Usage: catjob.py <jobqno>
"""
import sys, os, json
from config import load_config

def main():
    if len(sys.argv) != 2:
        print("Usage: catjob.py <jobqno>", file=sys.stderr)
        sys.exit(1)

    qno = sys.argv[1]

    config = load_config()
    yapo_root = config['yapo_root']
    jobs_dir = os.path.join(yapo_root, 'jobs')

    # Find the job in any state
    job_path = None
    state = None
    for st in ['ready', 'processing', 'pending', 'done', 'error']:
        path = os.path.join(jobs_dir, st, qno)
        if os.path.isdir(path):
            job_path = path
            state = st
            break

    if not job_path:
        print(f"Job {qno} not found", file=sys.stderr)
        sys.exit(1)

    # Job metadata
    with open(os.path.join(job_path, 'job.toml')) as f:
        job = json.load(f)

    print(f"Job {qno} (state: {state})")
    print(f"Type: {job.get('type')}, Model: {job.get('model', 'N/A')}")
    if job.get('tool_name'):
        print(f"Tool: {job['tool_name']}")
    print("---")

    # Output
    output_file = os.path.join(job_path, 'output.txt')
    if os.path.exists(output_file):
        with open(output_file) as f:
            print(f.read())
    else:
        print("No output yet.")

if __name__ == '__main__':
    main()
