#!/bin/bash
mkdir -p /home/yapo/yapo_root/jobs/{ready,processing,pending,done,error}
mkfifo /home/yapo/yapo_root/event.pipe 2>/dev/null || true
python3 yapo.py &
python3 dashboard.py



