# Northwind MCP Server — Reference Implementation

Entity-shaped MCP tools over MS SQL Server + the classic Northwind sample database.
Companion to `week09/theory/09-northwind-mcp-server.md` and `week09/practice/9-northwind-mcp-server.md`.

> **Rebuilding this live in class?** The step-by-step prompt sequence is in
> [`prompts/`](prompts/README.md).

## What's in here

| File | Purpose |
|---|---|
| `server.py` | The **entity MCP server** — one tool per aggregate root (Customer, Order, Employee). This is the reference implementation the theory argues for. |
| `raw_sql_server.py` | The **contrast server** for Exercise 9.5 — a single `run_query(sql)` tool. Deliberately the "wrong" design; use it to feel the difference. |
| `repository.py` | Plain Python functions that build aggregates. One function per tool. Parameterised queries only. |
| `models.py` | Pydantic models for `Customer`, `Order`, `OrderLine`, `Employee`, etc. |
| `test_repository.py` | Smoke tests. Run this **before** touching MCP — if it fails, MCP won't help. |
| `setup_readonly_login.sql` | Creates the `northwind_ro` SQL login with read-only permissions. Run once. |
| `claude_desktop_config.example.json` | Drop-in config for Claude Desktop. |
| `.mcp.example.json` | Drop-in config for Claude Code. |
| `requirements.txt` | `mcp[cli]`, `pyodbc`, `pydantic`. |

## Prerequisites

- **Windows** (Linux/macOS works — swap the ODBC driver name).
- **MS SQL Server** with Northwind attached. Free options: SQL Server 2022 Developer + the `instnwnd.sql` script (search: "Northwind and pubs sample databases GitHub").
- **Microsoft ODBC Driver 18 for SQL Server**.
- **Python 3.11+**.
- **Claude Desktop** (and/or Claude Code).

## Setup

### 1. Create the read-only SQL login

Open `setup_readonly_login.sql` in SSMS (or `sqlcmd`), change the password, run it.
Verify writes are rejected before continuing.

### 2. Install Python dependencies

```powershell
python -m pip install -r requirements.txt
```

### 3. Set the connection string

**PowerShell**:

```powershell
$env:NORTHWIND_CONN = "Driver={ODBC Driver 18 for SQL Server};Server=localhost;Database=Northwind;UID=northwind_ro;PWD=ChangeMe!Local42;TrustServerCertificate=yes"
```

**cmd.exe**:

```cmd
set NORTHWIND_CONN=Driver={ODBC Driver 18 for SQL Server};Server=localhost;Database=Northwind;UID=northwind_ro;PWD=ChangeMe!Local42;TrustServerCertificate=yes
```

If `python` on your PATH is not the interpreter you installed `requirements.txt`
into (e.g. you installed into a project `.venv`), also set:

```powershell
$env:NORTHWIND_PYTHON = "C:\path\to\.venv\Scripts\python.exe"
```

The project-level `.mcp.json` at the repository root uses that variable (see step 7).

### 4. Run the smoke tests

```powershell
python test_repository.py
```

Expected: 91 customers, ALFKI has 6 orders, order 10248 has 3 line items, 11 customers in Germany. If any assertion fails, fix the connection or the schema before moving on.

### 5. Inspect the MCP server

```powershell
npx @modelcontextprotocol/inspector python server.py
```

Open the URL it prints. Confirm five tools are listed, plus the `northwind://schema` resource. Call `get_customer` with `{"customer_id": "ALFKI"}` — you should see a full aggregate.

### 6. Plug into Claude Desktop

Copy `claude_desktop_config.example.json` to `%APPDATA%\Claude\claude_desktop_config.json` (merge if you already have one). Replace `C:\\ABSOLUTE\\PATH\\TO\\` with the real path. Restart Claude Desktop.

In a new chat, attach the `northwind://schema` resource (paperclip → Northwind → schema), then ask:

> "Show me our top 5 customers in Germany, and for the top one, list their last three orders."

Claude should chain `find_customers` → `get_customer`. No SQL in the transcript.

### 7. Plug into Claude Code

This repository ships a **project-level `.mcp.json`** at its root, so opening the repo
in Claude Code offers both servers (`northwind` and the Exercise 9.5 contrast server
`northwind-raw`). It deliberately contains no machine paths and no password — it reads
two environment variables instead:

| Variable | Purpose |
|---|---|
| `NORTHWIND_CONN` | ODBC connection string. **Required**; contains the login password, so it never goes into git. |
| `NORTHWIND_PYTHON` | Interpreter with `requirements.txt` installed. Defaults to `python` on PATH. |

Set them once for your user (new processes pick them up; a fresh terminal is enough):

```powershell
[Environment]::SetEnvironmentVariable('NORTHWIND_CONN', 'Driver={ODBC Driver 18 for SQL Server};Server=localhost;Database=Northwind;UID=northwind_ro;PWD=ChangeMe!Local42;TrustServerCertificate=yes', 'User')
[Environment]::SetEnvironmentVariable('NORTHWIND_PYTHON', 'C:\path\to\.venv\Scripts\python.exe', 'User')
```

Start Claude Code **from the repository root** (the server paths in `.mcp.json` are
relative to it), approve the servers when prompted, and check with:

```powershell
claude mcp list
```

If `NORTHWIND_CONN` is missing, `claude mcp list` prints
`Missing environment variables: NORTHWIND_CONN` and tools that touch the database fail.

For a one-off registration instead of the project file:

```powershell
claude mcp add northwind -e "NORTHWIND_CONN=..." -- C:\path\to\python.exe C:\absolute\path\to\server.py
```

`northwind-raw` is the deliberately "wrong" single-`run_query(sql)` design for
Exercise 9.5 — useful to compare against, not a model to copy.

## Tools exposed

| Tool | Returns |
|---|---|
| `get_customer(customer_id)` | Full `Customer` aggregate: company info + order summaries + lifetime value. |
| `get_order(order_id)` | Full `Order`: header + customer + employee + line items with product names. |
| `get_employee(employee_id)` | `Employee`: profile + manager + direct reports + YTD revenue. |
| `find_customers(country?, name_like?, limit?)` | Search results (thin summaries). |
| `get_top_customers(limit?)` | Top customers by all-time revenue. |

## Resources exposed

| URI | Purpose |
|---|---|
| `northwind://schema` | Entity map — attach to a chat so the model knows what exists. |

## Security notes

- **Read-only SQL login is the strongest single defense.** Even a prompt-injected instruction to write can't succeed against grants it doesn't have.
- **Parameterised queries everywhere.** No f-strings, no `%s`, no exceptions.
- **Hard limits on result sizes** (`limit` clamped, `fetchmany(200)` on raw SQL).
- **Logging** goes to `northwind-mcp.log` next to `server.py` — never `print()`, stdout is claimed by the MCP JSON-RPC transport.

See Exercise 9.7 in the practice file for guided attack scenarios against your own server.

## Troubleshooting

**"NORTHWIND_CONN env var is not set"** — set it in the same shell you launch `python server.py` from. For Claude Desktop, put it in the `env` block of `claude_desktop_config.json` (see the example).

**"IM002 [Microsoft][ODBC Driver Manager] Data source name not found"** — the ODBC Driver 18 isn't installed. Grab it from Microsoft's site.

**Claude Desktop doesn't show the server** — open Settings → Developer → MCP Logs. Path errors and Python errors show up here. Common cause: `python` not on PATH — use the full path to `python.exe`.

**`login failed for user 'northwind_ro'`** — run `setup_readonly_login.sql` again, or reset the password with `ALTER LOGIN northwind_ro WITH PASSWORD = '...'`.
