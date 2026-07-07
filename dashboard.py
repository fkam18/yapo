#!/usr/bin/env python3
"""
dashboard.py – Professional web dashboard for Yapo job queues.
Serves on http://0.0.0.0:3388
Auto‑refreshes the queue list every 2 seconds.
Shows sub‑jobs (tool children) indented under parent jobs.
Paginates job lists with most recent jobs first.
Theme is loaded from dashboard.theme.
Includes a job submission form with file attachments.
"""

import os, json, subprocess, sys, re, base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from config import load_config
from jobber import create_job, JOBS_DIR

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

<!-- ── Job Submission Modal ── -->
<div id="submit-modal" class="modal">
  <div class="modal-content">
    <div class="modal-header">
      <h2>Submit New Job</h2>
      <span class="modal-close" onclick="closeModal()">&times;</span>
    </div>
    <div class="modal-body">
      <label for="job-prompt">Prompt</label>
      <textarea id="job-prompt" rows="6" placeholder="Enter your job prompt..."></textarea>

      <div class="form-row">
        <div class="form-group">
          <label for="job-mtype">Model type</label>
          <select id="job-mtype">
            <option value="">Auto (router)</option>
            <option value="code">Code</option>
            <option value="others">Others</option>
            <option value="visual">Visual</option>
          </select>
        </div>
        <div class="form-group">
          <label for="job-name">Job name (optional)</label>
          <input type="text" id="job-name" placeholder="e.g. hello-world-test" />
        </div>
      </div>

      <div class="form-row">
        <div class="form-group">
          <label for="job-start-after">Start after (optional)</label>
          <input type="time" id="job-start-after" />
        </div>
        <div class="form-group">
          <label for="job-max-duration">Max duration (seconds, optional)</label>
          <input type="number" id="job-max-duration" placeholder="900" min="1" />
        </div>
      </div>

      <div class="form-row">
        <label>Attachments (optional)</label>
        <input type="file" id="job-attachments" multiple />
        <ul id="attachment-list" style="list-style:none;padding:0;margin-top:4px"></ul>
      </div>

      <div class="form-row" id="rag-section">
        <label style="margin-bottom:6px">RAG pre‑fetch (optional)</label>
        <div id="rag-entries">
          <div class="rag-entry">
            <select class="rag-tool">
              <option value="mem_read">mem_read</option>
              <option value="web_search">web_search</option>
            </select>
            <input type="text" class="rag-query" placeholder="Search query" />
            <button class="rag-remove" onclick="removeRagEntry(this)" title="Remove">&times;</button>
          </div>
        </div>
        <button class="rag-add" onclick="addRagEntry()">+ Add RAG</button>
      </div>
    </div>
    <div class="modal-footer">
      <span id="submit-status"></span>
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="submitJob()">Submit Job</button>
    </div>
  </div>
</div>

<!-- ── Main Layout ── -->
<div id="left">
  <div id="left-header">
    <h2>&#x26A1; Yapo Queues</h2>
    <div style="display:flex;align-items:center;gap:8px">
      <span class="badge" id="total-badge">0</span>
      <button class="new-job-btn" onclick="openModal()" title="New Job">+</button>
    </div>
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
var attachedFiles = [];

function openModal() { document.getElementById('submit-modal').style.display = 'flex'; }
function closeModal() { document.getElementById('submit-modal').style.display = 'none'; }
window.onclick = function(event) {
    if (event.target === document.getElementById('submit-modal')) closeModal();
};

// ── Attachment handling ──
document.getElementById('job-attachments').addEventListener('change', function(e) {
    attachedFiles = Array.from(e.target.files);
    var list = document.getElementById('attachment-list');
    list.innerHTML = '';
    attachedFiles.forEach(function(file, i) {
        var li = document.createElement('li');
        li.style.fontSize = '0.8rem';
        li.style.color = 'var(--text-muted)';
        li.innerHTML = file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB) <span onclick="removeAttachment(' + i + ')" style="cursor:pointer;color:var(--danger)">&times;</span>';
        list.appendChild(li);
    });
});

function removeAttachment(i) {
    attachedFiles.splice(i, 1);
    var list = document.getElementById('attachment-list');
    list.innerHTML = '';
    attachedFiles.forEach(function(file, idx) {
        var li = document.createElement('li');
        li.style.fontSize = '0.8rem';
        li.style.color = 'var(--text-muted)';
        li.innerHTML = file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB) <span onclick="removeAttachment(' + idx + ')" style="cursor:pointer;color:var(--danger)">&times;</span>';
        list.appendChild(li);
    });
}

// ── RAG entries ──
function addRagEntry() {
    var container = document.getElementById('rag-entries');
    var entry = document.createElement('div');
    entry.className = 'rag-entry';
    entry.innerHTML = '<select class="rag-tool"><option value="mem_read">mem_read</option><option value="web_search">web_search</option></select><input type="text" class="rag-query" placeholder="Search query" /><button class="rag-remove" onclick="removeRagEntry(this)" title="Remove">&times;</button>';
    container.appendChild(entry);
}
function removeRagEntry(btn) {
    var entries = document.querySelectorAll('.rag-entry');
    if (entries.length > 1) btn.parentElement.remove();
}

// ── Submit ──
function submitJob() {
    var prompt = document.getElementById('job-prompt').value.trim();
    if (!prompt) { alert('Please enter a prompt.'); return; }
    var mtype = document.getElementById('job-mtype').value;
    var name = document.getElementById('job-name').value.trim();
    var startAfter = document.getElementById('job-start-after').value;
    var maxDuration = document.getElementById('job-max-duration').value.trim();
    var ragEntries = document.querySelectorAll('.rag-entry');
    var rags = [];
    ragEntries.forEach(function(entry) {
        var tool = entry.querySelector('.rag-tool').value;
        var query = entry.querySelector('.rag-query').value.trim();
        if (query) rags.push(tool + ':' + query);
    });

    // Encode attachments as base64
    var attachments = [];
    var filesToProcess = attachedFiles.length;
    if (filesToProcess === 0) {
        sendSubmit({ prompt: prompt, mtype: mtype, name: name, start_after: startAfter, max_duration: maxDuration, rags: rags, attachments: [] });
        return;
    }

    attachedFiles.forEach(function(file) {
        var reader = new FileReader();
        reader.onload = function(e) {
            var base64content = e.target.result.split(',')[1];
            attachments.push({
                filename: file.name,
                content: base64content,
                mime: file.type || 'application/octet-stream'
            });
            filesToProcess--;
            if (filesToProcess === 0) {
                sendSubmit({ prompt: prompt, mtype: mtype, name: name, start_after: startAfter, max_duration: maxDuration, rags: rags, attachments: attachments });
            }
        };
        reader.readAsDataURL(file);
    });
}

function sendSubmit(payload) {
    var statusEl = document.getElementById('submit-status');
    statusEl.textContent = 'Submitting…';
    statusEl.style.color = 'var(--text-muted)';
    fetch('/api/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(function(response) { return response.json(); })
    .then(function(data) {
        if (data.error) { statusEl.textContent = data.error; statusEl.style.color = 'var(--danger)'; }
        else { statusEl.textContent = 'Job ' + data.qno + ' created!'; statusEl.style.color = 'var(--success)'; setTimeout(closeModal, 1000); }
    })
    .catch(function() { statusEl.textContent = 'Network error'; statusEl.style.color = 'var(--danger)'; });
}

// ── Queue / job display (unchanged) ──
function toggleQueue(header) { header.parentElement.classList.toggle('collapsed'); }

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
                currentRawJson = displayOutput;
                if (displayOutput) {
                    var cleaned = displayOutput.trim();
                    if (cleaned.startsWith('```')) {
                        var firstNewline = cleaned.indexOf('\n');
                        if (firstNewline !== -1) cleaned = cleaned.substring(firstNewline + 1);
                        if (cleaned.endsWith('```')) cleaned = cleaned.substring(0, cleaned.length - 3).trim();
                    }
                    try {
                        var parsed = JSON.parse(cleaned);
                        currentRawJson = JSON.stringify(parsed, null, 2);
                        if (parsed.answer) displayOutput = parsed.answer;
                        else if (parsed.done) displayOutput = parsed.answer || '[done]';
                        else if (parsed.tool) displayOutput = 'Tool call: ' + parsed.tool;
                    } catch(e) {}
                }
                currentDisplayText = displayOutput;

                let html = '';
                if (data.name) html += '<h2>' + escapeHtml(data.name) + ' <span style="color:var(--text-muted);font-size:0.8rem;font-weight:400">(#' + qno + ')</span></h2>';
                else html += '<h2>Job ' + qno + '</h2>';

                html += '<div class="meta">';
                html += '<span><b>State:</b> ' + data.state + '</span>';
                html += '<span><b>Job type:</b> ' + data.job_type + '</span>';
                if (data.model_type) html += '<span><b>Model type:</b> ' + data.model_type + '</span>';
                if (data.model_name) html += '<span><b>Model:</b> ' + data.model_name + '</span>';
                if (data.tool_name) html += '<span><b>Tool:</b> ' + data.tool_name + '</span>';
                if (data.start_after) html += '<span><b>Start after:</b> ' + data.start_after + '</span>';
                if (data.max_job_duration) html += '<span><b>Max duration:</b> ' + data.max_job_duration + 's</span>';
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
        btn.textContent = 'Show answer'; block.textContent = currentRawJson; currentDisplayText = currentRawJson;
    } else {
        btn.textContent = 'Show raw';
        try { var parsed = JSON.parse(currentRawJson); var answer = parsed.answer || parsed.tool || currentRawJson; block.textContent = answer; currentDisplayText = answer; }
        catch(e) { block.textContent = currentRawJson; currentDisplayText = currentRawJson; }
    }
}

function copyOutput() {
    navigator.clipboard.writeText(currentDisplayText).then(function() {
        var btn = document.querySelector('.copy-btn');
        var original = btn.textContent;
        btn.textContent = 'Copied!'; btn.style.background = 'var(--success)'; btn.style.color = '#fff'; btn.style.borderColor = 'var(--success)';
        setTimeout(function() { btn.textContent = original; btn.style.background = ''; btn.style.color = ''; btn.style.borderColor = ''; }, 1500);
    });
}

function escapeHtml(text) { return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function toggleSubs(qno) {
    let subs = document.getElementById('subs-' + qno);
    let toggle = document.getElementById('toggle-' + qno);
    if (subs.style.display === 'none') { subs.style.display = 'block'; toggle.textContent = '\u25BC'; expandedJobs[qno] = true; }
    else { subs.style.display = 'none'; toggle.textContent = '\u25B6'; expandedJobs[qno] = false; }
}

function restoreToggles() {
    Object.keys(expandedJobs).forEach(function(qno) {
        let subs = document.getElementById('subs-' + qno);
        let toggle = document.getElementById('toggle-' + qno);
        if (subs && toggle) {
            if (expandedJobs[qno]) { subs.style.display = 'block'; toggle.textContent = '\u25BC'; }
            else { subs.style.display = 'none'; toggle.textContent = '\u25B6'; }
        }
    });
    document.querySelectorAll('.toggle').forEach(function(el) { el.onclick = function() { toggleSubs(this.getAttribute('data-qno')); }; });
    document.querySelectorAll('.queue-header').forEach(function(el) { el.onclick = function() { toggleQueue(this); }; });
    Object.keys(pageNumbers).forEach(function(q) { showPage(q, pageNumbers[q] || 1); });
}

function refreshQueues() {
    fetch('/api/queues').then(response => response.text()).then(html => {
        document.getElementById('left-scroll').innerHTML = html;
        restoreToggles(); updateTotalBadge();
    });
}

function updateTotalBadge() {
    let total = 0;
    document.querySelectorAll('.count').forEach(function(el) { total += parseInt(el.textContent) || 0; });
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
                'model_type': job.get('model_type', ''),
                'tool_name': job.get('tool_name', ''),
                'name': job.get('name', ''),
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
    entry = f'<li>'
    children = info.get('children', [])
    if children:
        entry += f'<span class="toggle" id="toggle-{qno}" data-qno="{qno}" onclick="toggleSubs({qno})">\u25B6</span> '
    else:
        entry += f'<span style="width:14px;display:inline-block"></span> '
    label = f"{qno} - {info['name']}" if info.get('name') else str(qno)
    entry += f'<a onclick="loadJob(\'{qno}\')" title="Job {qno}">{escape_html(label)}</a>'
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


def escape_html(text):
    """Escape HTML entities in a string."""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


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

            model_type = job.get('model_type', '')
            model_name = ''
            if model_type:
                for m in config.get('models', []):
                    if m.get('type') == model_type:
                        model_name = m.get('name', '')
                        break

            output = None
            output_path = os.path.join(job_dir, 'output.txt')
            if os.path.exists(output_path):
                with open(output_path) as f:
                    output = f.read()
            return {
                'state': state,
                'name': job.get('name', ''),
                'job_type': job.get('type', ''),
                'model_type': model_type,
                'model_name': model_name,
                'tool_name': job.get('tool_name', ''),
                'start_after': job.get('start_after', ''),
                'max_job_duration': job.get('max_job_duration', ''),
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

        elif path == '/api/logs':
            log_path = '/tmp/yapo_scheduler.log'
            query = parse_qs(parsed.query)
            lines = int(query.get('lines', [100])[0])
            try:
                with open(log_path) as f:
                    all_lines = f.readlines()
                    recent = all_lines[-lines:]
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(''.join(recent).encode())
            except FileNotFoundError:
                self.send_response(503)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Log not available yet'}).encode())

        elif path == '/api/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())

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

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/submit':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            data = json.loads(body)

            prompt = data.get('prompt', '')
            mtype = data.get('mtype', '')
            name = data.get('name', '')
            start_after = data.get('start_after', '')
            max_duration = data.get('max_duration', '')
            rags = data.get('rags', [])
            attachments = data.get('attachments', [])

            # Validate attachments
            valid_attachments = []
            for att in attachments:
                if att.get('filename') and att.get('content'):
                    valid_attachments.append({
                        'filename': att['filename'],
                        'content': att['content'],
                        'mime': att.get('mime', 'application/octet-stream')
                    })

            try:
                # Create the job directly via jobber's Python API
                qno = create_job(
                    type='main',
                    state='pending' if rags else 'ready',
                    model_type=mtype,
                    prompt_text=prompt,
                    job_name=name,
                    start_after=start_after or None,
                    max_job_duration=int(max_duration) if max_duration else None,
                    attachments=valid_attachments
                )

                # Create RAG tool children if requested
                if rags:
                    for rag_spec in rags:
                        tool_name, query = rag_spec.split(':', 1)
                        tool_json_str = json.dumps({"tool": tool_name, "arguments": {"query": query}})
                        sub_qno = create_job(
                            type='tool',
                            state='pending',
                            parent=qno,
                            tool_name=tool_name,
                            tool_json=tool_json_str
                        )
                        move_job_folder(sub_qno, 'pending', 'ready')
                    move_job_folder(qno, 'pending', 'ready')

                response = {'success': True, 'qno': str(qno)}
            except Exception as e:
                response = {'error': str(e)}

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

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
