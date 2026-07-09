#!/usr/bin/env python3
"""
Convert a local config.toml (laptop paths) to config.toml.j2 (Docker paths + Jinja2 variables).
Reads from stdin, writes to stdout.
Usage: python3 convert-config.py < config.toml > config.toml.j2
"""

import sys, re

REPLACEMENTS = {
    # Paths: local laptop → Docker container
    '"/home/fkam/apps/yapo/yapo_mcp.py"': '"/app/yapo_mcp.py"',
    '"/home/fkam/apps/yapo/web_search_mcp.py"': '"/app/web_search_mcp.py"',
    '"/home/fkam/apps/yapo/shell_mcp.py"': '"/app/shell_mcp.py"',
    # Secrets path
    '"/home/fkam/apps/yapo/secrets/gpu/id_rsa"': '"/app/secrets/gpu/id_rsa"',
    # Workspace and runtime roots
    'workspace = "/home/fkam/apps"': 'workspace = "/home/master/apps"',
    'yapo_root = "/home/fkam/yapo"': 'yapo_root = "/home/yapo/yapo_root"',
    'path = "/home/fkam/apps/yapo/memory_db"': 'path = "/home/yapo/yapo_root/memory_db"',
    'YAPO_WORKSPACE = "/home/fkam/apps"': 'YAPO_WORKSPACE = "/home/master/apps"',
}

content = sys.stdin.read()

# Apply path replacements
for old, new in REPLACEMENTS.items():
    content = content.replace(old, new)

# Replace IPs and MAC with Ansible variables
content = content.replace('url = "http://192.168.0.180:11434"', 'url = "http://{{ nuc_ip }}:11434"')
content = content.replace('url = "http://192.168.0.158:8080"', 'url = "http://{{ gpu_ip }}:8080"')
content = content.replace('mac_address = "34:97:f6:31:88:ee"', 'mac_address = "{{ gpu_mac }}"')
content = content.replace('oper@192.168.0.158', 'oper@{{ gpu_ip }}')

# Wrap each prompt_template value in {% raw %}...{% endraw %}
pattern = r'(prompt_template = """\n)(.*?)(\n""")'

def wrapper(match):
    prefix = match.group(1)
    body = match.group(2)
    suffix = match.group(3)
    return f'{prefix}{{% raw %}}{body}{{% endraw %}}{suffix}'

content = re.sub(pattern, wrapper, content, flags=re.DOTALL)

print(content, end='')
