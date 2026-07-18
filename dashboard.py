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

import os, json, subprocess, sys, re, base64, time, shutil, signal
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from config import load_config
from jobber import create_job, JOBS_DIR
from log import log_read

from log import redirect_stderr
redirect_stderr("dashboard")

# Load Yapo configuration
config = load_config()
YAPO_ROOT = config['yapo_root']
JOBS_DIR = os.path.join(YAPO_ROOT, 'jobs')

# Named pipe for SSE events
SIGNAL_PIPE = os.path.join(YAPO_ROOT, 'event.pipe')
if not os.path.exists(SIGNAL_PIPE):
    os.mkfifo(SIGNAL_PIPE)

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
            {MODEL_OPTIONS}
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
        <input type="file" id="job-attachments" multiple style="display:none" />
        <button type="button" class="btn btn-secondary" onclick="document.getElementById('job-attachments').click()" style="font-size:0.85rem">Browse files...</button>
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
      <button class="btn btn-secondary" onclick="resetForm()">Reset</button>
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

// Tool call display state
var currentToolCallRaw = '';
var currentToolCallDisplay = '';
var currentToolCallSummary = '';

function openModal() {
    document.getElementById('job-prompt').value = '';
    document.getElementById('job-mtype').value = '';
    document.getElementById('job-name').value = '';
    document.getElementById('job-start-after').value = '';
    document.getElementById('job-max-duration').value = '';
    document.getElementById('job-attachments').value = '';
    document.getElementById('attachment-list').innerHTML = '';
    attachedFiles = [];
    document.getElementById('submit-status').textContent = '';
    document.getElementById('rag-entries').innerHTML = '<div class="rag-entry"><select class="rag-tool"><option value="mem_read">mem_read</option><option value="web_search">web_search</option></select><input type="text" class="rag-query" placeholder="Search query"><button class="rag-remove" onclick="removeRagEntry(this)" title="Remove">\u00d7</button></div>';
    document.getElementById('submit-modal').style.display = 'flex';
}

function resetForm() { openModal(); }
function closeModal() { document.getElementById('submit-modal').style.display = 'none'; }
window.onclick = function(event) {
    if (event.target === document.getElementById('submit-modal')) closeModal();
};

document.getElementById('job-attachments').addEventListener('change', function(e) {
    var newFiles = Array.from(e.target.files);
    attachedFiles = attachedFiles.concat(newFiles);
    var list = document.getElementById('attachment-list');
    list.innerHTML = '';
    attachedFiles.forEach(function(file, i) {
        var li = document.createElement('li');
        li.style.fontSize = '0.8rem';
        li.style.color = 'var(--text-muted)';
        li.innerHTML = file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB) <span onclick="removeAttachment(' + i + ')" style="cursor:pointer;color:var(--danger)">\u00d7</span>';
        list.appendChild(li);
    });
    this.value = '';
});

function removeAttachment(i) {
    attachedFiles.splice(i, 1);
    var list = document.getElementById('attachment-list');
    list.innerHTML = '';
    attachedFiles.forEach(function(file, idx) {
        var li = document.createElement('li');
        li.style.fontSize = '0.8rem';
        li.style.color = 'var(--text-muted)';
        li.innerHTML = file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB) <span onclick="removeAttachment(' + idx + ')" style="cursor:pointer;color:var(--danger)">\u00d7</span>';
        list.appendChild(li);
    });
}

function addRagEntry() {
    var container = document.getElementById('rag-entries');
    var entry = document.createElement('div');
    entry.className = 'rag-entry';
    entry.innerHTML = '<select class="rag-tool"><option value="mem_read">mem_read</option><option value="web_search">web_search</option></select><input type="text" class="rag-query" placeholder="Search query"><button class="rag-remove" onclick="removeRagEntry(this)" title="Remove">\u00d7</button>';
    container.appendChild(entry);
}
function removeRagEntry(btn) {
    var entries = document.querySelectorAll('.rag-entry');
    if (entries.length > 1) btn.parentElement.remove();
}

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
    var attachments = [];
    var filesToProcess = attachedFiles.length;
    if (filesToProcess === 0) {
        sendSubmit({ prompt: prompt, mtype: mtype, name: name, start_after: startAfter, max_duration: maxDuration, rags: rags, attachments: [] });
        return;
    }
    attachedFiles.forEach(function(file) {
        var reader = new FileReader();
        reader.onload = function(e) {
            attachments.push({
                filename: file.name,
                content: e.target.result.split(',')[1],
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
    statusEl.textContent = 'Submitting...';
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

function toggleQueue(header) { header.parentElement.classList.toggle('collapsed'); }

function showPage(queueName, page) {
  pageNumbers[queueName] = page;
  var allItems = document.querySelectorAll('#list-' + queueName + ' .job-page');
  allItems.forEach(function(el) { el.style.display = 'none'; });
  var pageEl = document.getElementById('page-' + queueName + '-' + page);
  if (pageEl) pageEl.style.display = 'block';
  var btns = document.querySelectorAll('#pager-' + queueName + ' button');
  btns.forEach(function(b) { b.classList.remove('active'); });
  var activeBtn = document.getElementById('btn-' + queueName + '-' + page);
  if (activeBtn) activeBtn.classList.add('active');
}

function loadJob(qno) {
    fetch('/api/job/' + qno)
        .then(function(response) { return response.json(); })
        .then(function(data) {
            var detail = document.getElementById('right');
            if (data.error) {
                detail.innerHTML = '<h2>Error</h2><p>' + data.error + '</p>';
            } else {
                // ── Process tool call if present ──
                if (data.tool_call) {
                    currentToolCallRaw = JSON.stringify(data.tool_call, null, 2);
                    var argsObj = {};
                    try { argsObj = JSON.parse(data.tool_call.function.arguments); } catch(e) {}
                    var argsStr = JSON.stringify(argsObj, null, 2);
                    currentToolCallSummary = 'Called tool ' + data.tool_call.function.name + ' with arguments:\n' + argsStr;
                    currentToolCallDisplay = currentToolCallSummary;
                } else {
                    currentToolCallRaw = '';
                    currentToolCallDisplay = '';
                    currentToolCallSummary = '';
                }

                // ── Process output ──
                var displayOutput = data.output || '';
                currentRawJson = displayOutput;
                if (displayOutput) {
                    var cleaned = displayOutput.trim();
                    // Remove markdown fences if present
                    if (cleaned.startsWith('```')) {
                        var firstNewline = cleaned.indexOf('\n');
                        if (firstNewline !== -1) cleaned = cleaned.substring(firstNewline + 1);
                        if (cleaned.endsWith('```')) cleaned = cleaned.substring(0, cleaned.length - 3).trim();
                    }
                    try {
                        var parsed = JSON.parse(cleaned);
                        currentRawJson = JSON.stringify(parsed, null, 2);
                        // ── spec13: structured message format ──
                        if (parsed.role === 'assistant') {
                            if (parsed.content) {
                                displayOutput = parsed.content;
                            } else if (parsed.tool_calls) {
                                var calls = parsed.tool_calls.map(function(tc) {
                                    return tc.function.name + '(' + tc.function.arguments + ')';
                                }).join(', ');
                                displayOutput = 'Tool calls: ' + calls;
                            } else {
                                displayOutput = '[assistant message with no content]';
                            }
                        } else if (parsed.role === 'tool') {
                            displayOutput = parsed.content || '[tool result]';
                        } else if (parsed.role) {
                            // other roles – just show content if available
                            displayOutput = parsed.content || JSON.stringify(parsed);
                        }
                        // ── fallback for legacy format (answer/done/tool) ──
                        else if (parsed.answer) {
                            displayOutput = parsed.answer;
                        } else if (parsed.done) {
                            displayOutput = parsed.answer || '[done]';
                        } else if (parsed.tool) {
                            displayOutput = 'Tool call: ' + parsed.tool;
                        }
                        // else keep displayOutput unchanged (e.g. simple text)
                    } catch(e) {
                        // Not JSON – keep as plain text
                    }
                }
                currentDisplayText = displayOutput;

                // ── Build HTML ──
                var html = '';
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

                // ── Tool Call section (if available) ──
                if (data.tool_call) {
                    html += '<div style="margin-top:16px">';
                    html += '<div style="display:flex;align-items:center;gap:10px">';
                    html += '<h3 style="margin:0">Tool Call</h3>';
                    html += '<button id="tool-raw-btn" class="raw-toggle" onclick="toggleToolRaw()">Show raw</button>';
                    html += '<button class="copy-btn" onclick="copyToolCall()">Copy</button>';
                    html += '</div>';
                    html += '<pre id="tool-call-block">' + escapeHtml(currentToolCallDisplay) + '</pre>';
                    html += '</div>';
                }

                // ── Output section ──
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
    var btn = document.getElementById('raw-btn');
    var block = document.getElementById('output-block');
    if (btn.textContent === 'Show raw') {
        btn.textContent = 'Show answer'; block.textContent = currentRawJson; currentDisplayText = currentRawJson;
    } else {
        btn.textContent = 'Show raw';
        try { var parsed = JSON.parse(currentRawJson);
            // Extract content if it's a structured message, else show raw
            var answer = (parsed && parsed.content) ? parsed.content : currentRawJson;
            if (parsed && parsed.role === 'assistant' && !parsed.content && parsed.tool_calls) {
                answer = 'Tool calls: ' + parsed.tool_calls.map(function(tc){return tc.function.name;}).join(', ');
            }
            block.textContent = answer; currentDisplayText = answer;
        }
        catch(e) { block.textContent = currentRawJson; currentDisplayText = currentRawJson; }
    }
}

function toggleToolRaw() {
    var btn = document.getElementById('tool-raw-btn');
    var block = document.getElementById('tool-call-block');
    if (btn.textContent === 'Show raw') {
        btn.textContent = 'Show summary'; block.textContent = currentToolCallRaw; currentToolCallDisplay = currentToolCallRaw;
    } else {
        btn.textContent = 'Show raw'; block.textContent = currentToolCallSummary; currentToolCallDisplay = currentToolCallSummary;
    }
}

function copyOutput() {
    const btn = document.querySelector('#output-block').parentElement.querySelector('.copy-btn');
    copyText(currentDisplayText, btn);
}
function copyToolCall() {
    const btn = document.querySelector('#tool-call-block').parentElement.querySelector('.copy-btn');
    copyText(currentToolCallDisplay, btn);
}
function copyText(text, btn) {
    if (!btn) return;
    const original = btn.textContent;
    const textSize = text.length;
    const sizeInMB = (textSize * 2) / (1024 * 1024);
    if (sizeInMB > 5) {
        if (!confirm(`Content is large (~${sizeInMB.toFixed(1)} MB). Copying may be slow or fail. Continue?`)) {
            return;
        }
    }
    try {
        if (textSize > 1000000) {
            btn.textContent = 'Preparing...';
            btn.disabled = true;
        }
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.cssText = 'position:fixed;opacity:0;left:-9999px;top:-9999px;';
        document.body.appendChild(textarea);
        textarea.select();
        const success = document.execCommand('copy');
        document.body.removeChild(textarea);
        if (success) {
            btn.textContent = 'Copied!';
            btn.style.background = 'var(--success)';
            btn.style.color = '#fff';
            btn.style.borderColor = 'var(--success)';
        }
    } catch (err) {
        btn.textContent = 'Failed!';
        btn.style.background = 'var(--danger)';
        btn.style.color = '#fff';
        btn.style.borderColor = 'var(--danger)';
    }
    setTimeout(() => {
        btn.textContent = original;
        btn.style.background = '';
        btn.style.color = '';
        btn.style.borderColor = '';
        btn.disabled = false;
    }, 1500);
}

function escapeHtml(text) { return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function toggleSubs(qno) {
    var subs = document.getElementById('subs-' + qno);
    var toggle = document.getElementById('toggle-' + qno);
    if (subs.style.display === 'none') { subs.style.display = 'block'; toggle.textContent = '\u25bc'; expandedJobs[qno] = true; }
    else { subs.style.display = 'none'; toggle.textContent = '\u25b6'; expandedJobs[qno] = false; }
}

function restoreToggles() {
    setTimeout(function() {
        Object.keys(expandedJobs).forEach(function(qno) {
            var subs = document.getElementById('subs-' + qno);
            var toggle = document.getElementById('toggle-' + qno);
            if (subs && toggle) {
                if (expandedJobs[qno]) { subs.style.display = 'block'; toggle.textContent = '\u25bc'; }
                else { subs.style.display = 'none'; toggle.textContent = '\u25b6'; }
            }
        });
        document.querySelectorAll('.toggle').forEach(function(el) {
            el.onclick = function() { toggleSubs(this.getAttribute('data-qno')); };
        });
        document.querySelectorAll('.queue-header').forEach(function(el) {
            el.onclick = function() { toggleQueue(this); };
        });
        Object.keys(pageNumbers).forEach(function(q) {
            showPage(q, pageNumbers[q] || 1);
        });
    }, 50);
}

function refreshQueues() {
    fetch('/api/queues').then(function(response) { return response.text(); }).then(function(html) {
        document.getElementById('left-scroll').innerHTML = html;
        restoreToggles(); updateTotalBadge();
    });
}

function updateTotalBadge() {
    var total = 0;
    document.querySelectorAll('.count').forEach(function(el) { total += parseInt(el.textContent) || 0; });
    document.getElementById('total-badge').textContent = total;
}

// SSE event-driven refresh
var eventSource = new EventSource('/api/stream');
eventSource.onmessage = function(event) {
    refreshQueues();
};
refreshQueues();
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

            # Read tool_call.json if present
            tool_call = None
            tool_call_path = os.path.join(job_dir, 'tool_call.json')
            if os.path.exists(tool_call_path):
                with open(tool_call_path) as f:
                    tool_call = json.load(f)

            return {
                'state': state,
                'name': job.get('name', ''),
                'job_type': job.get('type', ''),
                'model_type': model_type,
                'model_name': model_name,
                'tool_name': job.get('tool_name', ''),
                'start_after': job.get('start_after', ''),
                'max_job_duration': job.get('max_job_duration', ''),
                'output': output,
                'tool_call': tool_call
            }
    return {'error': 'Job not found'}


class DashboardHandler(BaseHTTPRequestHandler):

    def _safe_ws_path(self, rel_path):
        abs_path = os.path.realpath(os.path.join('/ws', rel_path.lstrip('/')))
        # Allow the workspace root itself or any path inside it
        if abs_path != '/ws' and not abs_path.startswith('/ws/'):
            raise ValueError("Path outside workspace")
        return abs_path

    def send_json(self, status, data):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        theme_css = load_theme()

        if path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            
            # Dynamically extract unique model types from config, omitting 'embed' and 'summarise' if needed
            model_types = []
            for m in config.get('models', []):
                mtype = m.get('type')
                if mtype and mtype not in model_types and mtype not in ('embed', 'summarise', 'router'):
                    model_types.append(mtype)
            
            # Generate the option elements string
            options_html = "\n".join([f'            <option value="{mtype}">{mtype}</option>' for mtype in model_types])
            
            queues_html = build_queue_html()
            html = HTML_TEMPLATE.replace('{QUEUES}', queues_html)\
                                 .replace('{THEME}', f'<style>{theme_css}</style>')\
                                 .replace('{MODEL_OPTIONS}', options_html)
            self.wfile.write(html.encode())

        elif path == '/api/queues':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            html = build_queue_html()
            self.wfile.write(html.encode())

        elif path == '/api/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                while True:
                    with open(SIGNAL_PIPE, 'rb') as f:
                        f.read(1)  # blocks until event
                    self.wfile.write(b"data: refresh\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        elif path == '/api/logs':
            query = parse_qs(parsed.query)
            lines = int(query.get('lines', [100])[0])
            result = log_read(lines)
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(result.encode())

        elif path == '/api/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())

        elif path == '/api/tree':
            tree = build_job_tree()
            result = {}
            for qno, info in tree.items():
                result[str(qno)] = {
                    'state': info['state'],
                    'job_type': info['job_type'],
                    'name': info.get('name', ''),
                    'model_type': info.get('model_type', ''),
                    'tool_name': info.get('tool_name', ''),
                    'parent': info['parent'],
                    'children': info['children']
                }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        elif path == '/api/mem/read':
            query = parse_qs(parsed.query)
            key = query.get('key', [''])[0]
            delete = query.get('del', ['false'])[0].lower() == 'true'
            compact = query.get('compact', ['false'])[0].lower() == 'true'
            top_k = int(query.get('top_k', ['15'])[0])
            
            from yapo_mcp import mem_read, mem_delete, mem_compact
            
            if compact:
                mem_compact({})
            
            if key:
                result = mem_read({'query': key, 'top_k': top_k})
                if delete:
                    mem_delete({'query': key, 'top_k': top_k})
            else:
                result = mem_read({'query': '', 'top_k': top_k})
                if delete:
                    mem_delete({'query': '', 'top_k': top_k})
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(result.encode())

        elif path == '/api/config':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            # Reload config to get latest (in case it was updated externally)
            current_config = load_config()
            self.wfile.write(json.dumps(current_config, indent=2).encode())

        elif path.startswith('/api/job/') and 'wait=true' in parsed.query:
            qno = path.split('/')[-1]
            query = parse_qs(parsed.query)
            timeout = int(query.get('timeout', [300])[0])
            
            start_time = time.time()
            while True:
                details = get_job_details(qno)
                state = details.get('state', '')
                
                if state in ('done', 'error'):
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(details).encode())
                    return
                
                elapsed = time.time() - start_time
                if timeout > 0 and elapsed >= timeout:
                    details['timed_out'] = True
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(details).encode())
                    return
                
                time.sleep(2)

        elif path.startswith('/api/job/') and path.endswith('/download'):
            qno = path.split('/')[-2]
            job_dir = None
            for state in STATES:
                d = os.path.join(JOBS_DIR, state, str(qno))
                if os.path.isdir(d):
                    job_dir = d
                    break
            if not job_dir:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Job not found'}).encode())
                return
            
            import tarfile, io
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode='w:gz') as tar:
                for root, dirs, files in os.walk(job_dir):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        arcname = os.path.relpath(fpath, job_dir)
                        tar.add(fpath, arcname=arcname)
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/gzip')
            self.send_header('Content-Disposition', f'attachment; filename="job_{qno}.tar.gz"')
            self.send_header('Content-Length', str(buf.tell()))
            self.end_headers()
            self.wfile.write(buf.getvalue())

        elif path.startswith('/api/job/'):
            qno = path.split('/')[-1]
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            details = get_job_details(qno)
            self.wfile.write(json.dumps(details).encode())

        # ── Workspace file endpoints ──
        elif path == '/api/ws/list':
            query = parse_qs(parsed.query)
            dir_rel = query.get('path', [''])[0]
            try:
                dir_path = self._safe_ws_path(dir_rel)
            except ValueError as e:
                self.send_json(403, {'error': str(e)})
                return

            if not os.path.isdir(dir_path):
                self.send_json(404, {'error': 'Not a directory'})
                return
            entries = []
            for name in sorted(os.listdir(dir_path)):
                full = os.path.join(dir_path, name)
                entries.append({
                    'name': name,
                    'type': 'directory' if os.path.isdir(full) else 'file',
                    'size': os.path.getsize(full) if os.path.isfile(full) else None
                })
            self.send_json(200, {'path': dir_rel, 'entries': entries})

        elif path == '/api/ws/download':
            query = parse_qs(parsed.query)
            file_rel = query.get('path', [''])[0]
            try:
                file_path = self._safe_ws_path(file_rel)
            except ValueError as e:
                self.send_json(403, {'error': str(e)})
                return

            if not os.path.isfile(file_path):
                self.send_json(404, {'error': 'File not found'})
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Disposition', f'attachment; filename="{os.path.basename(file_path)}"')
            self.send_header('Content-Length', str(os.path.getsize(file_path)))
            self.end_headers()
            with open(file_path, 'rb') as f:
                self.wfile.write(f.read())
        # ── Workspace file endpoints ──

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

            valid_attachments = []
            for att in attachments:
                if att.get('filename') and att.get('content'):
                    valid_attachments.append({
                        'filename': att['filename'],
                        'content': att['content'],
                        'mime': att.get('mime', 'application/octet-stream')
                    })

            try:
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
                        from jobber import move_job_folder
                        move_job_folder(sub_qno, 'pending', 'ready')
                    from jobber import move_job_folder
                    move_job_folder(qno, 'pending', 'ready')

                response = {'success': True, 'qno': str(qno)}
            except Exception as e:
                response = {'error': str(e)}

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        elif path == '/api/reload':
            # Send SIGHUP to yapo.py to reload config
            try:
                # Find yapo.py PID
                result = subprocess.run(['pgrep', '-f', 'python3 yapo.py'], capture_output=True, text=True)
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid:
                        os.kill(int(pid), signal.SIGHUP)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'message': 'Config reload signal sent'}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        elif path == '/api/mem/write':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            data = json.loads(body)
            text = data.get('text', '')
            prefix = data.get('prefix', '')
            
            from yapo_mcp import mem_write
            result = mem_write({'text': text, 'prefix': prefix})
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'message': result}).encode())

        elif path == '/api/config':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            data = json.loads(body)
            
            key = data.get('key', '')
            value = data.get('value', '')
            
            if key == 'CONN_OPENAI_DEBUG':
                if str(value).lower() in ('true', '1', 'yes'):
                    os.environ['CONN_OPENAI_DEBUG'] = 'true'
                else:
                    os.environ['CONN_OPENAI_DEBUG'] = 'false'
                import conn_openai
                conn_openai.DEBUG_DUMP = os.environ['CONN_OPENAI_DEBUG'] == 'true'
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'CONN_OPENAI_DEBUG': os.environ['CONN_OPENAI_DEBUG']}).encode())
            else:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': f'Unknown config key: {key}'}).encode())

        # ── Workspace upload / mkdir ──
        elif path == '/api/ws/upload':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            file_rel = data.get('path', '')
            content_b64 = data.get('content', '')
            try:
                file_path = self._safe_ws_path(file_rel)
            except ValueError as e:
                self.send_json(403, {'error': str(e)})
                return

            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            try:
                with open(file_path, 'wb') as f:
                    f.write(base64.b64decode(content_b64))
                self.send_json(200, {'success': True, 'path': file_rel})
            except Exception as e:
                self.send_json(500, {'error': str(e)})

        elif path == '/api/ws/mkdir':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            dir_rel = data.get('path', '')
            try:
                dir_path = self._safe_ws_path(dir_rel)
            except ValueError as e:
                self.send_json(403, {'error': str(e)})
                return
            os.makedirs(dir_path, exist_ok=True)
            self.send_json(200, {'success': True})

        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path.startswith('/api/job/'):
            qno = path.split('/')[-1]
            tree = build_job_tree()
            
            # Collect all descendants recursively
            to_delete = set()
            def collect_descendants(q):
                to_delete.add(int(q))
                for child in tree.get(int(q), {}).get('children', []):
                    collect_descendants(child)
            collect_descendants(qno)
            
            # Delete all collected jobs
            deleted_list = []
            for q in to_delete:
                for state in STATES:
                    job_dir = os.path.join(JOBS_DIR, state, str(q))
                    if os.path.isdir(job_dir):
                        shutil.rmtree(job_dir)
                        deleted_list.append(str(q))
                        break
            
            if deleted_list:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'deleted': deleted_list, 'count': len(deleted_list)}).encode())
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Job not found'}).encode())
        
        elif path.startswith('/api/jobs'):
            query = parse_qs(parsed.query)
            from_q = int(query.get('from', [0])[0])
            to_q = int(query.get('to', [0])[0])
            state_filter = query.get('state', [None])[0]
            
            deleted = []
            for state in (STATES if not state_filter else [state_filter]):
                state_dir = os.path.join(JOBS_DIR, state)
                if not os.path.isdir(state_dir):
                    continue
                for name in os.listdir(state_dir):
                    if name.isdigit():
                        q = int(name)
                        if q >= from_q and q <= to_q:
                            shutil.rmtree(os.path.join(state_dir, name))
                            deleted.append(str(q))
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'deleted': deleted, 'count': len(deleted)}).encode())

        elif path.startswith('/api/ws/delete'):
            query = parse_qs(parsed.query)
            file_rel = query.get('path', [''])[0]
            try:
                file_path = self._safe_ws_path(file_rel)
            except ValueError as e:
                self.send_json(403, {'error': str(e)})
                return
            if not os.path.exists(file_path):
                self.send_json(404, {'error': 'Not found'})
                return
            if os.path.isdir(file_path):
                if len(os.listdir(file_path)) > 0:
                    self.send_json(400, {'error': 'Directory not empty'})
                    return
                os.rmdir(file_path)
            else:
                os.remove(file_path)
            self.send_json(200, {'success': True})

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


from http.server import ThreadingHTTPServer

def main():
    server = ThreadingHTTPServer(('0.0.0.0', 3388), DashboardHandler)
    print("Yapo dashboard running at http://0.0.0.0:3388")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == '__main__':
    main()
