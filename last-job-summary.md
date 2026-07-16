## Complete API Changes Summary with Examples

---

### 1. **Memory Write API** (`POST /api/mem/write`)

**Endpoint**: `/api/mem/write`  
**Method**: POST  
**Content-Type**: application/json

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | Yes | Content to store in memory |
| `prefix` | string | No | Context tag prepended to stored text |

**Example - curl**:
```bash
# Write without prefix
curl -X POST http://app1.alt:3388/api/mem/write \
  -H "Content-Type: application/json" \
  -d '{"text":"The login function is in auth.py"}'

# Write with prefix
curl -X POST http://app1.alt:3388/api/mem/write \
  -H "Content-Type: application/json" \
  -d '{"text":"login function is in auth.py","prefix":"project-alpha"}'
```

**Example - CLI tool**:
```bash
# Write without prefix
echo "The login function is in auth.py" | python3 yapo_mem_write.py

# Write with prefix
echo "login function is in auth.py" | python3 yapo_mem_write.py --prefix "project-alpha"

# Write from file
cat facts.txt | python3 yapo_mem_write.py --prefix "research"
```

**Response**:
```json
{"success": true, "message": "Stored 1 lines."}
```

---

### 2. **Memory Read API** (`GET /api/mem/read`)

**Endpoint**: `/api/mem/read`  
**Method**: GET  
**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `key` | string | `""` | Search query (empty = read all) |
| `del` | boolean | `false` | Destructive read (delete after reading) |
| `compact` | boolean | `false` | Run compaction before reading |
| `top_k` | integer | `15` | Number of results to return |

**Example - curl**:
```bash
# Read matching entries
curl "http://app1.alt:3388/api/mem/read?key=login"

# Read with prefix matching
curl "http://app1.alt:3388/api/mem/read?key=project-alpha+login"

# Read all
curl "http://app1.alt:3388/api/mem/read?key="

# Read top 5 results
curl "http://app1.alt:3388/api/mem/read?key=login&top_k=5"

# Destructive read (read then delete)
curl "http://app1.alt:3388/api/mem/read?key=login&del=true"

# Compact then read
curl "http://app1.alt:3388/api/mem/read?key=login&compact=true"

# Delete all (destructive read-all)
curl "http://app1.alt:3388/api/mem/read?key=&del=true"
```

**Example - CLI tool**:
```bash
# Read matching entries
python3 yapo_mem_read.py -k "login"

# Read all
python3 yapo_mem_read.py -k ""

# Read with prefix
python3 yapo_mem_read.py -k "project-alpha login"

# Read top 5 results
python3 yapo_mem_read.py -k "login" --top-k 5

# Destructive read (read then delete)
python3 yapo_mem_read.py -k "login" -d

# Delete all
python3 yapo_mem_read.py -k "" -d

# Compact then read
python3 yapo_mem_read.py -k "login" --compact

# Full destructive read with compact
python3 yapo_mem_read.py -k "login" -d --compact
```

**Response Format** (plain text, bullet points):
```
- [project-alpha] login function is in auth.py
- [project-beta] login uses JWT tokens
- login authentication flow documented
```

---

### 3. **Memory Delete** (via `memory.py` CLI)

**Command**: `memory.py delete`

**Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--query`, `-q` | string | - | Query string (documents matching this will be deleted) |
| `--top-k`, `-k` | integer | `15` | Max documents to delete |
| `--read-all` | flag | - | Delete all documents |

**Example**:
```bash
# Delete matching entries (top 15 by default)
memory.py delete --query "login"

# Delete top 5 matching entries
memory.py delete --query "login" --top-k 5

# Delete all
memory.py delete --read-all

# Delete by prefix
memory.py delete --query "project-alpha"
```

**Response** (stderr):
```
Deleted 5 entries.
```
or
```
No matching entries to delete.
```
or
```
Deleted all 42 entries.
```

---

### 4. **Complete Workflow Examples**

#### Example 1: Store and Retrieve Knowledge
```bash
# Store knowledge with prefix
echo "The login function requires email and password" | \
  python3 yapo_mem_write.py --prefix "auth-module"

echo "Login uses JWT tokens with 1-hour expiry" | \
  python3 yapo_mem_write.py --prefix "auth-module"

# Query for login-related knowledge
python3 yapo_mem_read.py -k "login"
# Output:
# - [auth-module] The login function requires email and password
# - [auth-module] Login uses JWT tokens with 1-hour expiry
```

#### Example 2: Read Then Delete (Destructive Read)
```bash
# Read top 3 entries about login
python3 yapo_mem_read.py -k "login" --top-k 3
# Output shows 3 matching entries

# Delete exactly those 3 entries
python3 yapo_mem_read.py -k "login" --top-k 3 -d
# Output: same 3 entries (read before deletion)
# After: those 3 entries are removed
```

#### Example 3: Compact Database
```bash
# Before compact
python3 yapo_mem_read.py -k "login"
# Shows 10 entries including duplicates

# Compact and read
python3 yapo_mem_read.py -k "login" --compact
# Shows deduplicated results
```

#### Example 4: Delete All
```bash
# First check how many entries
python3 yapo_mem_read.py -k ""
# Shows all entries

# Delete everything
python3 yapo_mem_read.py -k "" -d
# Shows all entries before deletion

# Verify empty
python3 yapo_mem_read.py -k ""
# Shows nothing
```

---

### 5. **Advanced Usage with `top_k` Consistency**

The `top_k` parameter ensures destructive reads are predictable:

```bash
# Insert 10 documents with "login" in them
for i in $(seq 1 10); do
  echo "login test $i" | python3 yapo_mem_write.py --prefix "test"
done

# Read top 5 (returns 5 most relevant)
python3 yapo_mem_read.py -k "login" --top-k 5
# Shows exactly 5 entries

# Destructive read deletes exactly those 5
python3 yapo_mem_read.py -k "login" --top-k 5 -d
# Shows the same 5 entries, then deletes them

# Verify remaining 5 entries
python3 yapo_mem_read.py -k "login"
# Shows the remaining 5 entries
```

---

### 6. **Error Handling**

**Empty Query**:
```bash
# Read all
python3 yapo_mem_read.py -k ""
# Returns all documents

# Delete all
python3 yapo_mem_read.py -k "" -d
# Deletes all documents
```

**No Matches**:
```bash
python3 yapo_mem_read.py -k "nonexistent"
# Returns nothing (empty response)
```

**Invalid JSON**:
```bash
curl -X POST http://app1.alt:3388/api/mem/write \
  -H "Content-Type: application/json" \
  -d '{"text": "test"}'  # Missing closing brace
# Returns HTTP 400/500 error
```

---

### 7. **Docker Named Volume**

Memory persists across container restarts via Docker volume:
```bash
# Check volume exists
docker volume ls | grep yapo_data

# Backup memory DB
docker run --rm -v yapo_data:/data alpine tar czf - /data > memory_backup.tar.gz

# Restore memory DB
docker run --rm -i -v yapo_data:/data alpine tar xzf - -C /
```

**Note**: Only `docker compose down -v` removes the volume and data.

---

### 8. **Testing Script**

Run the baseline test:
```bash
# Default: 20 documents, top_k=5
./test_memory_api.sh

# Custom: 100 documents, top_k=10
./test_memory_api.sh 100 10

# Small test: 10 documents, top_k=3
./test_memory_api.sh 10 3
```

---

**Key Takeaway**: The API is consistent, deterministic, and supports both manual CLI usage and programmatic HTTP access. The `top_k` parameter ensures destructive reads are predictable, and the prefix feature enables document clustering for better organization.
