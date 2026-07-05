#!/usr/bin/env python3
"""
dashboard.py – Professional web dashboard for Yapo job queues.
Serves on http://0.0.0.0:3388
Auto‑refreshes the queue list every 2 seconds.
Shows sub‑jobs (tool children) indented under parent jobs.
Paginates job lists with most recent jobs first.
Theme is loaded from dashboard.theme.
"""

import os, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from config import load_config

# Load Yapo configuration
config = load_config()
YAPO_ROOT = config['yapo_root']
JOBS_DIR = os.path.join(YAPO_ROOT, 'jobs')

# Done and error first, then processing, pending, ready
STATES = ['done', 'error', 'processing', 'pending', 'ready']
JOBS_PER_PAGE = 10

# Theme file location (same directory as this script)
THEME_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.theme')


def load_theme():
    """Load the dashboard CSS theme from file."""
    if os.path.exists(THEME_FILE):
        with open(THEME_FILE) as f:
            return f.read()
    return "body { font-family: sans-serif; }"


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Yapo Dashboard</title>
{THEME}
</head>
<body>

<div id="left">
  <div id="left-header">
    <h2>&#x26A1; Yapo Queues</h2>
    <span class="badge" id="total-badge">0</span>
  </div>
  <div id="left-scroll">
    {QUEUES}
  </div>
</div>

<div class="divider"></div>

<div id="right">
  <div class="empty-state">
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
    </svg>
    <p>Select a job from the queue to see its details.</p>
  </div>
</div>

<script>
var expandedJobs = {};
var pageNumbers = {};
var currentRawJson = '';
var currentDisplayText = '';

function toggleQueue(header) {
  header.parentElement.classList.toggle('collapsed');
}

function showPage(queueName, page) {
  pageNumbers[queueName] = page;

  let allItems = document.querySelectorAll('#list-' + queueName + ' .job-page');
  allItems.forEach(function(el) { el.style.display = 'none'; });
  let pageEl = document.getElementById('page-' + queueName + '-' + page);
  if (pageEl) pageEl.style.display = 'block';

  let btns = document.querySelectorAll('#pager-' + queueName + ' button');
  btns.forEach(function(b) { b.classList.remove('active'); });
  let activeBtn = document.getElementById('btn-' + queueName + '-' + page);
  if (activeBtn) activeBtn.classList.add('active');
}

function loadJob(qno) {
    fetch('/api/job/' + qno)
        .then(response => response.json())
        .then(data => {
            let detail = document.getElementById('right');
            if (data.error) {
                detail.innerHTML = '<h2>Error</h2><p>' + data.error + '</p>';
            } else {
                var displayOutput = data.output || '';
                var isJsonOutput = false;
                currentRawJson = displayOutput;
                if (displayOutput) {
                    // Strip markdown fences that some models add
                    var cleaned = displayOutput.trim();
                    if (cleaned.startsWith('```')) {
                        var firstNewline = cleaned.indexOf('\n');
                        if (firstNewline !== -1) cleaned = cleaned.substring(firstNewline + 1);
                        if (cleaned.endsWith('```')) cleaned = cleaned.substring(0, cleaned.length - 3).trim();
                    }
                    try {
                        var parsed = JSON.parse(cleaned);
                        currentRawJson = JSON.stringify(parsed, null, 2);
                        isJsonOutput = true;
                        if (parsed.answer) {
                            displayOutput = parsed.answer;
                        } else if (parsed.done) {
                            displayOutput = parsed.answer || '[done]';
                        } else if (parsed.tool) {
                            displayOutput = 'Tool call: ' + parsed.tool;
                        }
                    } catch(e) {
                        // not JSON – use as‑is
                    }
                }
                currentDisplayText = displayOutput;

                let html = '<h2>Job ' + qno + '</h2>';
                html += '<div class="meta">';
                html += '<span><b>State:</b> ' + data.state + '</span>';
                html += '<span><b>Job type:</b> ' + data.job_type + '</span>';
                if (data.model_type) html += '<span><b>Model type:</b> ' + data.model_type + '</span>';
                if (data.model) html += '<span><b>Model:</b> ' + data.model + '</span>';
                if (data.tool_name) html += '<span><b>Tool:</b> ' + data.tool_name + '</span>';
                html += '</div>';

                if (data.output) {
                    html += '<div style="display:flex;align-items:center;gap:10px;margin-top:16px">';
                    html += '<h3 style="margin:0">Output</h3>';
                    html += '<button id="raw-btn" class="raw-toggle" onclick="toggleRaw()">Show raw</button>';
                    html += '<button class="copy-btn" onclick="copyOutput()">Copy</button>';
                    html += '</div>';
                    html += '<pre id="output-block">' + escapeHtml(displayOutput) + '</pre>';
                } else {
                    html += '<p style="color:var(--text-muted); margin-top:16px">No output yet.</p>';
                }
                detail.innerHTML = html;
            }
        });
}

function toggleRaw() {
    let btn = document.getElementById('raw-btn');
    let block = document.getElementById('output-block');
    if (btn.textContent === 'Show raw') {
        btn.textContent = 'Show answer';
        block.textContent = currentRawJson;
        currentDisplayText = currentRawJson;
    } else {
        btn.textContent = 'Show raw';
        // Re‑parse to get the answer back
        try {
            var parsed = JSON.parse(currentRawJson);
            var answer = parsed.answer || parsed.tool || currentRawJson;
            block.textContent = answer;
            currentDisplayText = answer;
        } catch(e) {
            block.textContent = currentRawJson;
            currentDisplayText = currentRawJson;
        }
    }
}

function copyOutput() {
    navigator.clipboard.writeText(currentDisplayText).then(function() {
        var btn = document.querySelector('.copy-btn');
        var original = btn.textContent;
        btn.textContent = 'Copied!';
        btn.style.background = 'var(--success)';
        btn.style.color = '#fff';
        btn.style.borderColor = 'var(--success)';
        setTimeout(function() {
            btn.textContent = original;
            btn.style.background = '';
            btn.style.color = '';
            btn.style.borderColor = '';
        }, 1500);
    }).catch(function() {
        alert('Failed to copy to clipboard');
    });
}

function escapeHtml(text) {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function toggleSubs(qno) {
    let subs = document.getElementById('subs-' + qno);
    let toggle = document.getElementById('toggle-' + qno);
    if (subs.style.display === 'none') {
        subs.style.display = 'block';
        toggle.textContent = '\u25BC';
        expandedJobs[qno] = true;
    } else {
        subs.style.display = 'none';
        toggle.textContent = '\u25B6';
        expandedJobs[qno] = false;
    }
}

function restoreToggles() {
    Object.keys(expandedJobs).forEach(function(qno) {
        let subs = document.getElementById('subs-' + qno);
        let toggle = document.getElementById('toggle-' + qno);
        if (subs && toggle) {
            if (expandedJobs[qno]) {
                subs.style.display = 'block';
                toggle.textContent = '\u25BC';
            } else {
                subs.style.display = 'none';
                toggle.textContent = '\u25B6';
            }
        }
    });
    document.querySelectorAll('.toggle').forEach(function(el) {
        el.onclick = function() {
            let qno = this.getAttribute('data-qno');
            toggleSubs(qno);
        };
    });
    document.querySelectorAll('.queue-header').forEach(function(el) {
        el.onclick = function() {
            toggleQueue(this);
        };
    });
    Object.keys(pageNumbers).forEach(function(q) {
        let page = pageNumbers[q] || 1;
        showPage(q, page);
    });
}

function refreshQueues() {
    fetch('/api/queues')
        .then(response => response.text())
        .then(html => {
            document.getElementById('left-scroll').innerHTML = html;
            restoreToggles();
            updateTotalBadge();
        });
}

function updateTotalBadge() {
    let total = 0;
    document.querySelectorAll('.count').forEach(function(el) {
        total += parseInt(el.textContent) || 0;
    });
    document.getElementById('total-badge').textContent = total;
}

setInterval(refreshQueues, 2000);
updateTotalBadge();
</script>
</body>
</html>"""


def build_job_tree():
    """Build a dict of job_number → {job_data, children: [child_job_numbers]}."""
    all_jobs = {}

    for state in STATES:
        state_dir = os.path.join(JOBS_DIR, state)
        if not os.path.isdir(state_dir):
            continue
        for name in os.listdir(state_dir):
            if not name.isdigit():
                continue
            qno = int(name)
            toml_path = os.path.join(state_dir, name, 'job.toml')
            if not os.path.exists(toml_path):
                continue
            with open(toml_path) as f:
                job = json.load(f)
            all_jobs[qno] = {
                'state': state,
                'job_type': job.get('type', ''),
                'model': job.get('model', ''),
                'tool_name': job.get('tool_name', ''),
                'parent': job.get('parent', 0),
                'children': []
            }

    for qno, info in all_jobs.items():
        parent = info['parent']
        if parent and parent in all_jobs:
            all_jobs[parent]['children'].append(qno)

    for info in all_jobs.values():
        info['children'].sort(reverse=True)

    return all_jobs


def build_queue_html():
    """Create the left‑panel HTML with pagination (most recent jobs first)."""
    tree = build_job_tree()

    state_jobs = {s: [] for s in STATES}
    for qno, info in tree.items():
        if info['parent'] == 0:
            state_jobs.setdefault(info['state'], []).append(qno)

    html = ""
    for state in STATES:
        jobs = sorted(state_jobs.get(state, []), reverse=True)
        total_count = len(jobs) + sum(len(tree[q]['children']) for q in jobs if q in tree)

        html += f'<div class="queue">\n'
        html += f'<div class="queue-header" onclick="toggleQueue(this)">\n'
        html += f'<h3><span class="state-dot {state}"></span> {state.capitalize()} <span class="count">{total_count}</span></h3>\n'
        html += f'<span class="arrow">\u25BC</span>\n'
        html += f'</div>\n'
        html += f'<div class="queue-body">\n'

        if not jobs:
            html += '<p style="padding:8px 14px; color:var(--text-muted); font-size:0.85rem">Empty</p>\n'
        else:
            pages = (len(jobs) + JOBS_PER_PAGE - 1) // JOBS_PER_PAGE
            html += f'<ul class="job-list" id="list-{state}">\n'
            for page in range(1, pages + 1):
                start = (page - 1) * JOBS_PER_PAGE
                end = start + JOBS_PER_PAGE
                display = 'block' if page == 1 else 'none'
                html += f'<div class="job-page" id="page-{state}-{page}" style="display:{display}">\n'
                for qno in jobs[start:end]:
                    html += build_job_entry(qno, tree[qno], tree, depth=0)
                html += '</div>\n'
            html += '</ul>\n'

            if pages > 1:
                html += f'<div class="pagination" id="pager-{state}">\n'
                for page in range(1, pages + 1):
                    active = 'active' if page == 1 else ''
                    html += f'<button id="btn-{state}-{page}" class="{active}" onclick="showPage(\'{state}\', {page})">{page}</button>\n'
                html += '</div>\n'

        html += '</div>\n'
        html += '</div>\n'

    return html


def build_job_entry(qno, info, tree, depth=0):
    """Build the HTML for a single job and its sub‑jobs recursively."""
    entry = ""
    entry += f'<li>'

    children = info.get('children', [])
    if children:
        entry += f'<span class="toggle" id="toggle-{qno}" data-qno="{qno}" onclick="toggleSubs({qno})">\u25B6</span> '
    else:
        entry += f'<span style="width:14px;display:inline-block"></span> '

    entry += f'<a onclick="loadJob(\'{qno}\')">{qno}</a>'
    if info.get('job_type') == 'tool':
        entry += f' <span class="tool-tag">{info.get("tool_name", "tool")}</span>'

    entry += '</li>\n'

    if children:
        entry += f'<ul class="sub-jobs" id="subs-{qno}" style="display:none">\n'
        for child_qno in sorted(children, reverse=True):
            if child_qno in tree:
                entry += build_job_entry(child_qno, tree[child_qno], tree, depth + 1)
        entry += f'</ul>\n'

    return entry


def get_job_details(qno):
    """Return a dict with job details for the given queue number."""
    for state in STATES:
        job_dir = os.path.join(JOBS_DIR, state, str(qno))
        if os.path.isdir(job_dir):
            toml_path = os.path.join(job_dir, 'job.toml')
            if not os.path.exists(toml_path):
                return {'error': 'job.toml not found'}
            with open(toml_path) as f:
                job = json.load(f)

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

        theme_css = load_theme()

        if path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            queues_html = build_queue_html()
            html = HTML_TEMPLATE.replace('{QUEUES}', queues_html).replace('{THEME}', f'<style>{theme_css}</style>')
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
        pass


def main():
    server = HTTPServer(('0.0.0.0', 3388), DashboardHandler)
    print("Yapo dashboard running at http://0.0.0.0:3388")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == '__main__':
    main()
