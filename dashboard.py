#!/usr/bin/env python3
"""
dashboard.py – Simple web dashboard for Yapo job queues.
Serves on http://localhost:3388
Auto‑refreshes the queue list every second.
"""
import os, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from config import load_config

# Load Yapo configuration
config = load_config()
YAPO_ROOT = config['yapo_root']
JOBS_DIR = os.path.join(YAPO_ROOT, 'jobs')
STATES = ['ready', 'processing', 'pending', 'done', 'error']

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Yapo Dashboard</title>
<style>
  body { font-family: Arial, sans-serif; margin: 0; display: flex; height: 100vh; }
  #left { width: 300px; background: #f5f5f5; padding: 15px; overflow-y: auto; border-right: 1px solid #ccc; }
  #right { flex: 1; padding: 20px; overflow-y: auto; }
  h2 { margin-top: 0; }
  .queue { margin-bottom: 15px; }
  .queue h3 { margin: 5px 0; font-size: 1.1em; }
  .job-list { list-style: none; padding: 0; }
  .job-list li { margin: 2px 0; }
  .job-list a { text-decoration: none; color: #06c; cursor: pointer; }
  .job-list a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div id="left">
  <h2>Job Queues</h2>
  {QUEUES}
</div>
<div id="right">
  <h2>Job Details</h2>
  <p>Click a job number to see its details.</p>
</div>
<script>
function loadJob(qno) {
    fetch('/api/job/' + qno)
        .then(response => response.json())
        .then(data => {
            let detail = document.getElementById('right');
            if (data.error) {
                detail.innerHTML = '<h2>Error</h2><p>' + data.error + '</p>';
            } else {
                let html = '<h2>Job ' + qno + ' (' + data.state + ')</h2>';
                html += '<p><b>Job type:</b> ' + data.job_type + ' | <b>Model type:</b> ' + (data.model_type || 'N/A') + '</p>';
                html += '<p><b>Model:</b> ' + (data.model || 'N/A') + '</p>';
                if (data.tool_name) html += '<p><b>Tool:</b> ' + data.tool_name + '</p>';
                if (data.output) {
                    html += '<h3>Output</h3><pre>' + escapeHtml(data.output) + '</pre>';
                } else {
                    html += '<p>No output yet.</p>';
                }
                detail.innerHTML = html;
            }
        });
}

function escapeHtml(text) {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Auto‑refresh the queue list every second
function refreshQueues() {
    fetch('/api/queues')
        .then(response => response.text())
        .then(html => {
            document.getElementById('left').innerHTML = '<h2>Job Queues</h2>' + html;
        });
}
setInterval(refreshQueues, 1000);
</script>
</body>
</html>"""

def build_queue_html():
    """Create the left‑panel HTML showing all queues and their jobs."""
    html = ""
    for state in STATES:
        state_dir = os.path.join(JOBS_DIR, state)
        if not os.path.isdir(state_dir):
            continue
        jobs = sorted([n for n in os.listdir(state_dir) if n.isdigit()], key=int)
        count = len(jobs)
        html += f'<div class="queue">\n'
        html += f'<h3>{state.capitalize()} ({count})</h3>\n'
        if jobs:
            html += '<ul class="job-list">\n'
            for job in jobs:
                html += f'<li><a onclick="loadJob(\'{job}\')">{job}</a></li>\n'
            html += '</ul>\n'
        else:
            html += '<p>Empty</p>\n'
        html += '</div>\n'
    return html

def get_job_details(qno):
    """Return a dict with job details for the given queue number."""
    for state in STATES:
        job_dir = os.path.join(JOBS_DIR, state, qno)
        if os.path.isdir(job_dir):
            toml_path = os.path.join(job_dir, 'job.toml')
            if not os.path.exists(toml_path):
                return {'error': 'job.toml not found'}
            with open(toml_path) as f:
                job = json.load(f)

            # Resolve model type from config
            model_type = ''
            model_name = job.get('model', '')
            if model_name:
                for m in config.get('models', []):
                    if m.get('name') == model_name:
                        model_type = m.get('type', '')
                        break

            output = None
            output_path = os.path.join(job_dir, 'output.txt')
            if os.path.exists(output_path):
                with open(output_path) as f:
                    output = f.read()
            return {
                'state': state,
                'job_type': job.get('type', ''),
                'model': model_name,
                'model_type': model_type,
                'tool_name': job.get('tool_name', ''),
                'output': output
            }
    return {'error': 'Job not found'}

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            queues_html = build_queue_html()
            html = HTML_TEMPLATE.replace('{QUEUES}', queues_html)
            self.wfile.write(html.encode())

        elif path == '/api/queues':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            html = build_queue_html()
            self.wfile.write(html.encode())

        elif path.startswith('/api/job/'):
            qno = path.split('/')[-1]
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            details = get_job_details(qno)
            self.wfile.write(json.dumps(details).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress access logs

def main():
    server = HTTPServer(('', 3388), DashboardHandler)
    print("Yapo dashboard running at http://localhost:3388")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()

if __name__ == '__main__':
    main()
