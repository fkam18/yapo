#!/bin/bash
# Start scheduler in background, redirect stderr to a shared log file
python3 yapo.py 2>/tmp/yapo_scheduler.log &

# Start dashboard in foreground
python3 dashboard.py
