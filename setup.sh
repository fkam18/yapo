#!/bin/bash
YAPO_ROOT=$(python3 -c "from config import get_yapo_root; print(get_yapo_root())")
mkdir -p "$YAPO_ROOT/jobs/"{ready,processing,pending,done,error}
echo "Yapo root initialized at $YAPO_ROOT"
