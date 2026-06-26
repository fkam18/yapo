#!/usr/bin/env python3
"""
Memory summarization tool - section-by-section extraction
Usage:
  summarise.py --input <file> --output <file>              # document mode (default)
  summarise.py --input <file> --mode turn                   # LLM turn mode
  cat file.txt | summarise.py --mode document
"""

import os
import sys
import json
import re
import argparse
import urllib.request
import urllib.error
from typing import Optional, List

from config import load_config, get_model


# ============================================================
# Ollama API
# ============================================================

def call_ollama(url: str, model: str, prompt: str, options: dict) -> Optional[str]:
    """Call Ollama API"""
    api_url = f"{url}/api/generate"
    
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options
    }
    
    data = json.dumps(payload).encode('utf-8')
    
    try:
        req = urllib.request.Request(
            api_url, data=data,
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('response', '').strip()
    except Exception as e:
        print(f"  ✗ API error: {e}", file=sys.stderr)
        return None


# ============================================================
# Title extraction (document mode)
# ============================================================

def extract_document_title(url: str, model: str, text: str, options: dict) -> str:
    """Ask the LLM to generate a short title for the document."""
    preview = text[:1000]
    
    prompt = f"""What is the project or product name in this document?
Output ONLY the name, 2-4 words maximum. Use spaces between words.
Example: "mrelay v2" not "MercuryRelayV2"

Document:
{preview}

Name:"""
    
    title_opts = {**options, 'num_predict': 15}
    title = call_ollama(url, model, prompt, title_opts)
    
    if title and len(title) > 2:
        title = title.strip().strip('"\'').strip()
        title = re.sub(r'^(title:|name:|#)\s*', '', title, flags=re.IGNORECASE)
        return title[:60]
    
    return "Document"


# ============================================================
# Chunking
# ============================================================

def chunk_by_headers(text: str) -> List[dict]:
    """Split markdown by headers into sections"""
    sections = []
    current_header = "Overview"
    current_content = []
    
    for line in text.split('\n'):
        header_match = re.match(r'^#{1,6}\s+(.+)', line)
        if header_match:
            if current_content:
                content_text = '\n'.join(current_content).strip()
                if content_text:
                    sections.append({
                        'header': current_header,
                        'content': content_text
                    })
            current_header = header_match.group(1)
            current_content = []
        else:
            current_content.append(line)
    
    if current_content:
        content_text = '\n'.join(current_content).strip()
        if content_text:
            sections.append({
                'header': current_header,
                'content': content_text
            })
    
    return sections


def chunk_by_paragraphs(text: str, max_chunk_chars: int = 800) -> List[dict]:
    """
    Split text into chunks by paragraph boundaries when no markdown headers exist.
    Groups paragraphs together up to max_chunk_chars.
    """
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current = []
    current_len = 0
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        para_len = len(para)
        
        if current_len + para_len > max_chunk_chars and current:
            chunks.append({
                'header': _guess_section_title(current[0]),
                'content': '\n\n'.join(current)
            })
            current = [para]
            current_len = para_len
        else:
            current.append(para)
            current_len += para_len
    
    if current:
        chunks.append({
            'header': _guess_section_title(current[0]),
            'content': '\n\n'.join(current)
        })
    
    return chunks


def _guess_section_title(paragraph: str) -> str:
    """Try to guess a section title from the first sentence of a paragraph."""
    first_sentence = paragraph.split('.')[0][:60].strip()
    
    if len(first_sentence) > 40:
        words = first_sentence.split()[:5]
        first_sentence = ' '.join(words)
    
    first_sentence = re.sub(r'^(The|A|An|This|It)\s+', '', first_sentence)
    
    return first_sentence[:50]


# ============================================================
# Cleaning
# ============================================================

def clean_facts(text: str) -> str:
    """Strip markdown artifacts and formatting from extracted facts"""
    
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'(?<!\n)\*([^*]+)\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    
    lines = []
    for line in text.split('\n'):
        line = line.strip()
        if not line or re.match(r'^[-\s]*$', line):
            continue
        
        line = re.sub(r'^>\s*', '', line)
        line = re.sub(r'^[-*]\s*[-*]\s*', '- ', line)
        
        if line.startswith('- ') or line.startswith('* '):
            line = '- ' + line[2:].strip()
        elif line.startswith('-') and not line.startswith('- '):
            line = '- ' + line[1:].strip()
        elif line.startswith('*') and not line.startswith('* '):
            line = '- ' + line[1:].strip()
        
        line = re.sub(r'\s*\([^)]*\)\s*$', '', line)
        if line.startswith('(') and line.endswith(')'):
            line = line[1:-1]
        
        line = re.sub(r'\s+', ' ', line)
        line = line.rstrip(':')
        lines.append(line)
    
    seen = set()
    unique_lines = []
    for line in lines:
        normalized = line.lower().strip('- ')
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_lines.append(line)
    
    return '\n'.join(unique_lines)


# ============================================================
# Extraction modes
# ============================================================

def extract_document_section(url: str, model: str, header: str, content: str, options: dict) -> str:
    """Extract technical facts from a document section."""
    if len(content.strip()) < 30:
        return ""
    
    text = content[:2000]
    
    prompt = f"""Extract the key technical facts from this text as bullet points.
Rules:
- Each line must start with "- "
- Include specific values: port numbers, endpoints, versions, file paths, commands
- Each fact should be unique — do not repeat the same information
- Skip vague statements, keep only concrete details
- If a value is unknown, skip that line entirely

{text}

Facts:"""
        
    facts = call_ollama(url, model, prompt, options)
    
    if not facts or len(facts) < 5:
        return ""
    
    facts = clean_facts(facts)
    
    if not facts or len(facts) < 5:
        return ""
    
    lines = facts.split('\n')
    contextual_lines = []
    for line in lines:
        line = line.strip()
        if not line.startswith('- '):
            continue
        
        fact_content = line[2:].strip()
        
        if fact_content.lower().startswith(header.lower()):
            contextual_lines.append(f"- {fact_content}")
        else:
            contextual_lines.append(f"- {header}: {fact_content}")
            
    return '\n'.join(contextual_lines)


def extract_llm_turn(url: str, model: str, content: str, options: dict) -> str:
    """Summarise an LLM agent turn into key points for memory."""
    if len(content.strip()) < 20:
        return ""
    
    # Strip code blocks before summarising — keep a note that code was written
    text = re.sub(r'```.*?```', '[code written]', content, flags=re.DOTALL)[:1500]
    
    prompt = f"""Reduce this LLM agent turn to exactly 3 bullet points. Be concise.
- Goal: what was being attempted
- Actions: tools called, files changed, or code written (one line)
- Status: complete, or in progress with next step

Turn:
{text}

Summary:"""
    
    summary = call_ollama(url, model, prompt, options)
    
    if not summary or len(summary.strip()) < 5:
        return ""
    
    summary = clean_facts(summary)
    
    if not summary or len(summary.strip()) < 5:
        return ""
    
    # Keep first 5 lines max
    lines = summary.split('\n')[:5]
    summary = '\n'.join(lines)
    
    return summary


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Summarise text for memory embedding")
    parser.add_argument('--input', '-i', type=str, help='Input file (default: stdin)')
    parser.add_argument('--output', '-o', type=str, help='Output file (default: stdout)')
    parser.add_argument('--mode', '-m', choices=['document', 'turn'], default='document',
                        help='document: full extraction with sections, turn: brief LLM turn summary')
    parser.add_argument('--prefix', '-p', type=str, default=None,
                        help='Context prefix for bullet points (document mode)')
    parser.add_argument('--no-auto-prefix', action='store_true',
                        help='Skip automatic prefix detection')
    args = parser.parse_args()
    
    # Read input
    if args.input:
        with open(args.input) as f:
            input_text = f.read().strip()
    elif not sys.stdin.isatty():
        input_text = sys.stdin.read().strip()
    else:
        print("Error: No input. Use --input <file> or pipe to stdin.", file=sys.stderr)
        sys.exit(1)
    
    if not input_text:
        print("Error: Empty input", file=sys.stderr)
        sys.exit(1)
    
    # Load model config from config.toml
    model_cfg = get_model('summarise')
    if not model_cfg:
        print("Error: No 'summarise' model defined in config.toml", file=sys.stderr)
        sys.exit(1)
    
    url = model_cfg.get('url', 'http://localhost:11434')
    model = model_cfg['name']
    
    # Build options dict from model config
    options = {
        "temperature": model_cfg.get('temperature', 0.0),
        "num_predict": model_cfg.get('max_tokens', 120),
        "stop": ["\n\n\n", "\n- \n", "- -"],
    }
    
    if 'repeat_penalty' in model_cfg:
        options['repeat_penalty'] = model_cfg['repeat_penalty']
    if 'repeat_last_n' in model_cfg:
        options['repeat_last_n'] = model_cfg['repeat_last_n']
    
    print(f"Model: {model} @ {url}", file=sys.stderr)
    print(f"Mode: {args.mode}", file=sys.stderr)
    print(f"Input: {len(input_text)} chars", file=sys.stderr)
    
    # ============================================================
    # TURN MODE
    # ============================================================
    if args.mode == 'turn':
        output_text = extract_llm_turn(url, model, input_text, options)
        
        if not output_text:
            print("Error: Failed to summarise turn", file=sys.stderr)
            sys.exit(1)
        
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output_text)
            print(f"Wrote {len(output_text.split(chr(10)))} lines to {args.output}", file=sys.stderr)
        else:
            print(output_text)
        
        return
    
    # ============================================================
    # DOCUMENT MODE
    # ============================================================
    
    if not args.prefix and not args.no_auto_prefix:
        print("Generating document title...", file=sys.stderr)
        args.prefix = extract_document_title(url, model, input_text, options)
        print(f"Title: {args.prefix}", file=sys.stderr)
    elif args.prefix:
        print(f"Prefix: {args.prefix}", file=sys.stderr)
    
    sections = chunk_by_headers(input_text)
    
    if len(sections) <= 1:
        para_sections = chunk_by_paragraphs(input_text)
        if len(para_sections) > 1:
            sections = para_sections
            print(f"Using paragraph-based chunking", file=sys.stderr)
    
    total = len(sections)
    
    if total == 0:
        print("Error: No sections found", file=sys.stderr)
        sys.exit(1)
    
    print(f"Sections: {total}", file=sys.stderr)
    
    all_facts = []
    for i, section in enumerate(sections, 1):
        header = section['header']
        content = section['content']
        
        print(f"  [{i}/{total}] {header[:60]}...", file=sys.stderr, end=' ')
        
        if len(content) < 30:
            print("(skipped - too short)", file=sys.stderr)
            continue
        
        facts = extract_document_section(url, model, header, content, options)
        
        if facts:
            all_facts.append(facts)
            print(f"✓ ({len(facts.split(chr(10)))} points)", file=sys.stderr)
        else:
            print("✗ (no facts extracted)", file=sys.stderr)
    
    if args.prefix:
        prefixed_facts = []
        for fact_block in all_facts:
            for line in fact_block.split('\n'):
                if line.startswith('- ') and args.prefix.lower() not in line.lower():
                    line = f"- {args.prefix}: {line[2:]}"
                prefixed_facts.append(line)
        all_facts = ['\n'.join(prefixed_facts)]
    
    if not all_facts:
        print("Error: No facts extracted from document", file=sys.stderr)
        sys.exit(1)
    
    output_text = '\n'.join(all_facts)
    total_lines = len(output_text.split('\n'))
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output_text)
        print(f"Wrote {total_lines} lines to {args.output}", file=sys.stderr)
    else:
        print(output_text)
        print(f"Done: {total_lines} bullet points extracted", file=sys.stderr)


if __name__ == "__main__":
    main()
