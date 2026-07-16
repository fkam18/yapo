#!/usr/bin/env python3
"""
Memory tool – stores each line (bullet point) separately.
Uses batch embedding for speed.

Examples:
  # Write with context prefix
  memory.py write --input facts.txt --prefix "project-alpha"
  memory.py write --prefix "meeting-notes" < notes.txt
  cat data.txt | memory.py write --prefix "research"
  
  # Read (query automatically matches context prefixes too)
  memory.py read --query "authentication"
  memory.py read --query "project-alpha deployment" --top-k 10
  
  # Compact to remove duplicates
  memory.py compact
"""

import sys, json, uuid, urllib.request, urllib.error, re, argparse
from datetime import datetime, timezone

import chromadb
from chromadb.config import Settings

from config import load_config, get_model, get_db_path, get_collection as get_collection_name


def get_embeddings_batch(url: str, model: str, texts: list) -> list:
    """Fetch embeddings for multiple texts in one API call."""
    api_url = f"{url}/api/embed"
    payload = {"model": model, "input": texts}
    data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(
            api_url, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["embeddings"]
    except Exception as e:
        print(f"Batch embedding error: {e}", file=sys.stderr)
        sys.exit(1)


def get_embedding(url: str, model: str, text: str) -> list:
    """Fetch single embedding (for queries)."""
    return get_embeddings_batch(url, model, [text])[0]


def get_collection():
    """Get or create ChromaDB collection from config."""
    client = chromadb.PersistentClient(
        path=get_db_path(),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(name=get_collection_name())


def cmd_write(args):
    """Store text lines into memory with optional context prefix."""
    # Read input
    if args.input:
        with open(args.input) as f:
            text = f.read().strip()
    elif not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    else:
        print("Error: No input. Use --input <file> or pipe to stdin.", file=sys.stderr)
        sys.exit(1)

    if not text:
        print("Error: empty input", file=sys.stderr)
        sys.exit(1)

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        print("Error: no non-empty lines", file=sys.stderr)
        sys.exit(1)

    # Add context prefix to each line if provided
    prefix = args.prefix or ""
    if prefix:
        prefixed_lines = [f"[{prefix}] {line}" for line in lines]
    else:
        prefixed_lines = lines

    # Get embedding model config
    model_cfg = get_model('embed')
    if not model_cfg:
        print("Error: No 'embed' model defined in config.toml", file=sys.stderr)
        sys.exit(1)

    url = model_cfg.get('url', 'http://localhost:11434')
    model = model_cfg['name']

    print(f"Embedding {len(prefixed_lines)} lines in one batch via {model}...", file=sys.stderr)
    if prefix:
        print(f"Context prefix: [{prefix}]", file=sys.stderr)
    else:
        print("No context prefix", file=sys.stderr)

    embeddings = get_embeddings_batch(url, model, prefixed_lines)

    collection = get_collection()
    timestamp = datetime.now(timezone.utc).isoformat()
    ids = [str(uuid.uuid4()) for _ in prefixed_lines]
    metadatas = [{"timestamp": timestamp, "source": args.input or "stdin"} for _ in prefixed_lines]

    collection.add(ids=ids, embeddings=embeddings, documents=prefixed_lines, metadatas=metadatas)

    print(f"Stored {len(prefixed_lines)} lines.", file=sys.stderr)

def cmd_delete(args):
    """Delete documents matching a query (same semantics as read)."""
    if args.read_all:
        # Delete all
        collection = get_collection()
        all_ids = collection.get()['ids']
        if all_ids:
            collection.delete(ids=all_ids)
            print(f"Deleted all {len(all_ids)} entries.", file=sys.stderr)
        else:
            print("No entries to delete.", file=sys.stderr)
        return

    query = args.query
    if not query:
        print("Error: empty query", file=sys.stderr)
        sys.exit(1)

    n_results = args.top_k

    # Get embedding
    model_cfg = get_model('embed')
    if not model_cfg:
        print("Error: No 'embed' model defined in config.toml", file=sys.stderr)
        sys.exit(1)
    url = model_cfg.get('url', 'http://localhost:11434')
    model = model_cfg['name']
    emb = get_embedding(url, model, query)

    collection = get_collection()
    results = collection.query(
        query_embeddings=[emb],
        n_results=n_results,
    )
    ids = results.get('ids', [[]])[0]
    if ids:
        collection.delete(ids=ids)
        print(f"Deleted {len(ids)} entries.", file=sys.stderr)
    else:
        print("No matching entries to delete.", file=sys.stderr)

def cmd_read(args):
    # Read all documents if --read-all is set
    if getattr(args, 'read_all', False):
        collection = get_collection()
        all_docs = collection.get(include=["documents"])
        docs = all_docs.get('documents', [])
        if docs:
            output_lines = [f"- {doc}" for doc in docs]
            print('\n'.join(output_lines))
        else:
            print("No documents in memory.", file=sys.stderr)
        return
    """Query memory for similar content."""
    # Read query
    if args.query:
        query = args.query
    elif args.input:
        with open(args.input) as f:
            query = f.read().strip()
    elif not sys.stdin.isatty():
        query = sys.stdin.read().strip()
    else:
        print("Error: No query. Use --query, --input, or pipe to stdin.", file=sys.stderr)
        sys.exit(1)

    if not query:
        print("Error: empty query", file=sys.stderr)
        sys.exit(1)

    # Get embedding model config
    model_cfg = get_model('embed')
    if not model_cfg:
        print("Error: No 'embed' model defined in config.toml", file=sys.stderr)
        sys.exit(1)

    url = model_cfg.get('url', 'http://localhost:11434')
    model = model_cfg['name']
    n_results = args.top_k

    emb = get_embedding(url, model, query)
    collection = get_collection()

    results = collection.query(
        query_embeddings=[emb],
        n_results=n_results,
        include=["documents"],
    )

    docs = results.get("documents", [[]])[0]
    if not docs:
        print("No matching memories.", file=sys.stderr)
        return

    output_lines = [f"- {doc}" for doc in docs]
    output_text = '\n'.join(output_lines)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(output_text)
        print(f"Wrote {len(docs)} results to {args.output}", file=sys.stderr)
    else:
        print(output_text)


def cmd_compact(args):
    """Remove exact and near-duplicate lines from the collection."""
    collection = get_collection()
    
    results = collection.get(include=["documents", "metadatas"])
    if not results["ids"]:
        print("Collection is empty.", file=sys.stderr)
        return
    
    ids = results["ids"]
    docs = results["documents"] or []
    
    print(f"Checking {len(ids)} documents for duplicates...", file=sys.stderr)
    
    # Step 1: Remove exact duplicates
    seen_texts = {}
    exact_keep = set()
    exact_remove = []
    
    for i, doc_id in enumerate(ids):
        text = docs[i] if i < len(docs) else ""
        if text in seen_texts:
            exact_remove.append(doc_id)
        else:
            seen_texts[text] = doc_id
            exact_keep.add(doc_id)
    
    # Step 2: Remove near-duplicates (Jaccard similarity > 80%)
    remaining = [(doc_id, docs[i]) for i, doc_id in enumerate(ids) if doc_id in exact_keep]
    
    def jaccard(a: str, b: str) -> float:
        words_a = set(re.findall(r'\b\w+\b', a.lower()))
        words_b = set(re.findall(r'\b\w+\b', b.lower()))
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / len(words_a | words_b)
    
    near_keep = set()
    near_remove = []
    
    for doc_id, text in remaining:
        is_dup = False
        for kept_id, kept_text in [(k, t) for k, t in remaining if k in near_keep]:
            if jaccard(text, kept_text) > 0.8:
                is_dup = True
                break
        if not is_dup:
            near_keep.add(doc_id)
        else:
            near_remove.append(doc_id)
    
    all_remove = list(set(exact_remove + near_remove))
    
    if all_remove:
        collection.delete(ids=all_remove)
        print(f"Removed {len(all_remove)} duplicates (exact: {len(exact_remove)}, near: {len(near_remove)})", file=sys.stderr)
        print(f"Kept {len(ids) - len(all_remove)} documents.", file=sys.stderr)
    else:
        print("No duplicates found.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Vector memory store with context prefix support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Write with context prefix
  memory.py write --input facts.txt --prefix "project-alpha"
  memory.py write --prefix "meeting-notes" < notes.txt
  cat data.txt | memory.py write --prefix "research"
  
  # Read (query matches context prefixes too)
  memory.py read --query "authentication"
  memory.py read --query "project-alpha deployment" --top-k 10
  
  # Compact to remove duplicates
  memory.py compact
        """
    )
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # write
    p_write = subparsers.add_parser(
        'write', 
        help='Store text into memory (optionally with context prefix)',
        description='Store text lines into memory with optional context prefix.',
        epilog="""
Examples:
  memory.py write --input facts.txt --prefix "project-alpha"
  memory.py write --prefix "meeting-notes" < notes.txt
  cat data.txt | memory.py write --prefix "research"
  echo "Remember to deploy" | memory.py write --prefix "tasks"
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p_write.add_argument('--input', '-i', type=str, help='Input file (default: stdin)')
    p_write.add_argument('--prefix', '-m', type=str, 
                        help='Context prefix label (e.g., --prefix "project-alpha" adds "[project-alpha]" to each stored line)')

    # read
    p_read = subparsers.add_parser(
        'read', 
        help='Query memory for similar content',
        description='Query memory for similar content (context prefixes are automatically matched).',
        epilog="""
Examples:
  memory.py read --query "authentication"
  memory.py read --query "project-alpha"  # Matches entries with that prefix
  memory.py read -i query.txt -o results.txt
  echo "deployment strategy" | memory.py read -k 10
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p_read.add_argument('--input', '-i', type=str, help='Query from file')
    p_read.add_argument('--query', '-q', type=str, help='Query string')
    p_read.add_argument('--output', '-o', type=str, help='Output file (default: stdout)')
    p_read.add_argument('--top-k', '-k', type=int, default=15, help='Number of results (default: 15)')
    p_read.add_argument('--read-all', action='store_true', help='Return all stored documents')

    # compact
    p_compact = subparsers.add_parser(
        'compact', 
        help='Remove duplicate entries',
        description='Remove exact and near-duplicate lines from the collection.',
        epilog="""
Example:
  memory.py compact  # Removes duplicates and shows count
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # delete
    p_delete = subparsers.add_parser(
        'delete',
        help='Delete documents matching a query',
        description='Delete documents using the same semantics as read.',
        epilog="""
Examples:
  memory.py delete --query "authentication" --top-k 5
  memory.py delete --read-all
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p_delete.add_argument('--query', '-q', type=str, help='Query string (documents matching this will be deleted)')
    p_delete.add_argument('--top-k', '-k', type=int, default=15, help='Max documents to delete (default: 15)')
    p_delete.add_argument('--read-all', action='store_true', help='Delete all documents')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == 'write':
        cmd_write(args)
    elif args.command == 'read':
        cmd_read(args)
    elif args.command == 'compact':
        cmd_compact(args)
    elif args.command == 'delete':
        cmd_delete(args)


if __name__ == "__main__":
    main()
