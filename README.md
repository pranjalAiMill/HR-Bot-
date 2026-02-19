# HR-BOT

A Flask-based HR assistant that routes each user query through a small **LangGraph** workflow to produce an answer using:

- **RAG over HR policies** (FAISS vector index built from `policies/*.txt`)
- **Text-to-SQL** over a local **SQLite** HR database (`db/hr.db`)
- **Action execution** for leave applications via a separate **MCP (Flask) server**

The main API also exposes a Slack slash-command endpoint and uses a simple Slack-user → employee mapping for basic role-based access.

## What you get

- **/chat**: simple JSON API (mostly useful for policy questions unless you provide user context)
- **/slack/command**: Slack slash-command handler that adds user context (emp_id + role)
- Local **SQLite** HR data store seeded from CSVs in `data/`
- Local **FAISS** vector store for policies in `vector_db/faiss_index`
- A separate local service (`mcp_server`) that actually mutates leave balances and logs leave applications

---

## Repository structure

- **`app.py`**
  - Main Flask API (port `8080`)
  - Initializes DB and vector store at startup
  - Exposes `/chat` and `/slack/command`

- **`graph/`**
  - **`hr_graph.py`**: LangGraph workflow definition
  - **`state.py`**: `HRState` (typed state passed between nodes)

- **`agents/`** (LangGraph nodes)
  - **`planner_agent.py`**: decides route (`RAG` / `SQL` / `ACTION`) and enforces some RBAC rules
  - **`rag_agent.py`**: retrieves relevant policy chunks from FAISS
  - **`text2sql_agent.py`**: generates and executes a `SELECT` query against SQLite
  - **`action_agent.py`**: extracts leave request payload and calls the MCP server
  - **`summarizer_agent.py`**: produces final natural-language answer (and appends citations when present)

- **`mcp_server/`**
  - **`server.py`**: separate Flask server (port `9000`)
  - **`auth.py`**: token auth via `X-MCP-TOKEN` header
  - **`routes/leave.py`**: leave-apply endpoint that updates SQLite + persists a CSV audit log + sends email

- **`utils/`**
  - **`db_loader.py`**: creates tables and seeds from CSV
  - **`vector_store.py`**: loads FAISS index and exposes a retriever
  - **`schema_prompt.py`**: converts `config/schema.json` into an LLM prompt for Text-to-SQL
  - **`user_context.py`**: resolves Slack user ID → `{ emp_id, role }` via `config/user_mapping.json`
  - **`emailer.py`**: SMTP email helper
  - **`logger.py`**: consistent stdout logger

- **`policies/`**: source policy text files used for RAG
- **`scripts/build_vector_index.py`**: builds `vector_db/faiss_index` from `policies/*.txt`
- **`data/`**: seed CSVs for SQLite + leave log export
- **`db/hr.db`**: SQLite database file
- **`vector_db/faiss_index/`**: persisted FAISS vector index

---

## High-level architecture

### 1) Main API server (Flask, port 8080)

At startup (`app.py`):

- Calls `build_db()` (creates tables + seeds from `data/*.csv`)
- Calls `get_retriever()` (ensures FAISS index exists and can be loaded)

Then for each request it invokes the LangGraph workflow (`hr_graph.invoke(state)`).

### 2) LangGraph workflow

Defined in `graph/hr_graph.py`:

- Entry: `planner`
- Conditional edge based on `state["steps"]`:
  - `RAG` → `rag` → `summary`
  - `SQL` → `sql` → `summary`
  - `ACTION` → `action` → `summary`
- Finish: `summary`

**Important state fields** (see `graph/state.py`):

- Input: `query`, `user`, `slack_user_id`
- Planner: `steps`, `error`
- RAG: `rag_context`, `citations`
- SQL: `sql_result`
- Action: `action_status`
- Output: `final_answer`

### 3) MCP server (Flask, port 9000)

The MCP server is called by `agents/action_agent.py` when a query requires applying leave.

- Endpoint: `POST http://localhost:9000/leave/apply`
- Auth: `X-MCP-TOKEN` header must match `MCP_TOKEN` from `.env`

This endpoint:

- Validates employee + leave balance in SQLite
- Deducts leave balance
- Inserts an audit row into `leave_log`
- Exports the full `leave_log` table to `data/leave_log.csv`
- Attempts to send a confirmation email (email failures do **not** fail the API)

---

## Data model

SQLite DB location: `db/hr.db` (created/updated by `utils/db_loader.py`).

Tables created:

- `employees(emp_id, name, department, email)`
- `salaries(emp_id, salary)`
- `leaves(emp_id, balance)`
- `leave_log(id, emp_id, created_at, total_leaves_before, leaves_requested, start_date, end_date, total_leaves_after)`

Schema prompt source of truth for Text-to-SQL: `config/schema.json`.

Seed files (loaded if present):

- `data/employees.csv`
- `data/salaries.csv`
- `data/leaves.csv`

---

## RAG (policy Q&A)

- Source documents: `policies/*.txt`
- Build step: `scripts/build_vector_index.py`
- Persisted index: `vector_db/faiss_index`

At runtime (`utils/vector_store.py`):

- Loads FAISS index from disk
- Exposes `db.as_retriever()`
- `rag_agent` retrieves chunks and passes combined `rag_context` + `citations` into the summarizer                

---

## RBAC / user context

Slack requests add user context via `utils/user_context.py`, which loads:

- `config/user_mapping.json`

`planner_agent` enforces some rules (examples):

- If query mentions `salary` and user is not HR:
  - user can only view own salary (checks for `my/mine` or their `emp_id` in query)
- Leave application for others is blocked for non-HR

`text2sql_agent` also requires `user.emp_id`. If it’s missing, it returns an `error` object that the summarizer converts into a user-visible warning.

---

## Setup

### 1) Create and activate a virtual environment

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2) Install dependencies

```powershell
pip install -r requirements.txt
```

Note: `scripts/build_vector_index.py` imports `langchain_text_splitters`. If you see:

- `ModuleNotFoundError: No module named 'langchain_text_splitters'`

Install it:

```powershell
pip install langchain-text-splitters
```

### 3) Configure environment variables

Create a `.env` file in the project root.

LLM config (choose one provider):

- `LLM_PROVIDER=openai`
  - `OPENAI_API_KEY=...`
  - `OPENAI_MODEL=...`

or

- `LLM_PROVIDER=gemini`
  - `GEMINI_API_KEY=...`
  - `GEMINI_MODEL=...`

MCP server auth:

- `MCP_TOKEN=some-secret-token`

Optional SMTP email (for leave confirmation emails):

- `SMTP_HOST=...`
- `SMTP_PORT=587`
- `SMTP_USER=...`
- `SMTP_PASSWORD=...`
- `SMTP_FROM=...`

---

## Build the policy vector index

Run once (or whenever you change `policies/*.txt`):

```powershell
python scripts/build_vector_index.py
```

This produces/updates: `vector_db/faiss_index/`.

---

## Running the application

You typically run **two servers** locally:

### 1) Start MCP server (leave actions)

```powershell
python mcp_server/server.py
```

Runs on: `http://localhost:9000`

### 2) Start main API server

```powershell
python app.py
```

Runs on: `http://localhost:8080`

---

## API usage

### `POST /chat`

- URL: `http://localhost:8080/chat`
- Body:

```json
{ "query": "What is the leave policy?" }
```

This route only passes `{ query }` into the graph (no user identity). That’s fine for many policy questions, but SQL/action flows may require user context.

### `POST /slack/command`

This is intended for Slack slash commands.

- URL: `http://localhost:8080/slack/command`
- Expects Slack form fields like:
  - `text` (user query)
  - `user_id` (Slack user id)
  - `response_url`

The handler:

- Looks up Slack `user_id` in `config/user_mapping.json`
- Invokes the graph in a background thread
- Posts the final answer back to Slack using `response_url`

---

## How a request is processed (nuts & bolts)

1) **Input arrives** (API or Slack)

- `/chat` creates state: `{ "query": ... }`
- `/slack/command` creates state: `{ "query", "user", "slack_user_id" }`

2) **Planner decides the route** (`agents/planner_agent.py`)

- Deterministic routing rules first:
  - policy questions → `RAG`
  - "apply" → `ACTION`
  - "balance" / "how many" / "salary" → `SQL`
- Otherwise falls back to LLM planner that must return JSON like `["RAG"]`

3) **One of the execution agents runs**

- **RAG** (`agents/rag_agent.py`)
  - retrieves policy chunks
  - stores: `rag_context`, `citations`

- **SQL** (`agents/text2sql_agent.py`)
  - builds a schema prompt from `config/schema.json`
  - asks LLM for a `SELECT` statement
  - executes it via SQLAlchemy on SQLite
  - stores: `sql_result`

- **ACTION** (`agents/action_agent.py`)
  - uses LLM to extract `{ start_date, days }`
  - enforces `emp_id` from trusted user context (employees can only apply for themselves)
  - calls MCP server `/leave/apply`
  - stores: `action_status`

4) **Summarizer produces the final answer** (`agents/summarizer_agent.py`)

- If any agent returned `error`, it stops and returns a warning message
- Otherwise it uses the gathered context to produce `final_answer`
- If citations exist, it appends them as `References:`

---

## Extending the project

- Add new policy documents:
  - Drop `.txt` files into `policies/`
  - Rebuild index: `python scripts/build_vector_index.py`

- Change DB schema or tables:
  - Update `utils/db_loader.py` (table creation)
  - Update `config/schema.json` (Text-to-SQL prompt)

- Add a new capability step:
  - Create a new agent in `agents/`
  - Add a new node + routing edge in `graph/hr_graph.py`
  - Add/extend planner rules in `agents/planner_agent.py`

---

## Troubleshooting

- **Vector index not found**
  - Error: `Vector index not found. Run scripts/build_vector_index.py first.`
  - Fix: run `python scripts/build_vector_index.py`

- **Missing user context** (common via `/chat` for SQL/action)
  - Error message: `User identity could not be determined.`
  - Fix: use `/slack/command` with a mapped Slack user, or extend `/chat` to accept user context

- **MCP leave apply returns 403**
  - Ensure `.env` has `MCP_TOKEN=...`
  - Ensure request includes `X-MCP-TOKEN` header (the action agent sets it)

- **Emails not sending**
  - The system logs `SMTP configuration missing` when SMTP env vars are absent
  - Email failures do not break leave application
