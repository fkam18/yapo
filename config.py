import os, sys
from typing import Optional, Dict, List
try:
    import tomllib
except ImportError:
    import tomli as tomllib

_config = None

def load_config():
    global _config
    if _config is not None:
        return _config
    path = os.environ.get('YAPO_CONFIG', 'config.toml')
    if not os.path.exists(path):
        print("config.toml not found", file=sys.stderr)
        sys.exit(1)
    with open(path, 'rb') as f:
        _config = tomllib.load(f)
    # ensure yapo_root has a default
    if 'yapo_root' not in _config:
        _config['yapo_root'] = os.path.expanduser('~/yapo')
    return _config

def get_yapo_root():
    return load_config().get('yapo_root', os.path.expanduser('~/yapo'))

def get_server(name):
    config = load_config()
    for s in config.get('servers', []):
        if s['name'] == name:
            return s
    return None

def get_tool(name):
    config = load_config()
    for t in config.get('tools', []):
        if t['name'] == name:
            return t
    return None

def get_model(type: str) -> Optional[dict]:
    """
    Get the model config for a given type.
    Returns dict with name, server, url, and all model options.
    """
    config = load_config()
    models = config.get('models', [])
    servers = {s['name']: s for s in config.get('servers', [])}

    for model in models:
        if model.get('type') == type:
            # Resolve server URL
            server_name = model.get('server', '')
            server = servers.get(server_name, {})
            model['url'] = server.get('url', 'http://localhost:11434')
            model['max_jobs'] = server.get('max_jobs', 1)
            return model

    return None


def get_db_path() -> str:
    """Get the database path from config."""
    config = load_config()
    return config.get('database', {}).get('path', './memory_db')


def get_collection() -> str:
    """Get the collection name from config."""
    config = load_config()
    return config.get('database', {}).get('collection', 'conversations')

def get_model_for_type(type):
    config = load_config()
    for m in config.get('models', []):
        if m['type'] == type:
            return m
    return None
