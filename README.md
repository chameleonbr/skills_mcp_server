

# 🛠️ Skills MCP Server

![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-green)
![MCP](https://img.shields.io/badge/MCP-Capable-orange)
![Agno](https://img.shields.io/badge/Agno-Agent_Skills-blueviolet)

A centralized, sandboxed Model Context Protocol (MCP) server designed to manage, execute, and expose advanced **Agent Skills** to any MCP-capable framework or low-code platform (like n8n, custom agents, etc.).

## 💡 The Problem It Solves

Currently, many popular orchestration frameworks and low-code platforms only support basic **tools** or **MCP**. However, modern AI agents require fully encapsulated, complex **agent skills** (prompts, tool chains, and logic combined). **Agno framework** natively supports these advanced agent skills, but getting them into platforms like n8n or custom agentic systems has historically been a challenge.

**`skills_mcp_server` is the bridge.** By wrapping Agno skills in an isolated FastAPI server and exposing them via the universal Model Context Protocol (MCP), **any** system that supports MCP can now instantly leverage complex agent skills.

---

## ✨ Key Advantages

* **🎯 Selective Skill Exposure (Context Optimization):** Install a massive library of skills on the server, but expose only the exact ones a specific agent needs. By tailoring the skill list per agent, you prevent LLM context bloat, save tokens, and drastically improve agent accuracy.
* **🗄️ Centralized Skill Hub:** Stop scattering custom scripts and functions across different repositories or n8n nodes. Manage your entire organization's AI capabilities in one unified, easily updatable server.
* **🔒 Sandboxed Execution:** All skills run in an isolated environment. You can safely install third-party community skills without risking the integrity of your host application or primary infrastructure.
* **📦 Automatic Dependency Isolation:** Skills that include a `requirements.txt` file are automatically provisioned with a dedicated virtual environment using `uv`. This ensures perfect isolation and clean uninstalls without bloating the main server's dependencies.
* **🧠 Powered by Agno:** Go beyond simple tools. Leverage Agno to build rich, stateful agent skills that can handle complex multi-step reasoning before returning the final payload via MCP.
* **📦 Dynamic Hot-Loading:** Add, update, or remove skills on the fly using `.zip` files, custom `.skill` packages, or direct download URLs without ever restarting the server.

---

## 🏗️ Architecture Concept

The system operates on a dual-interface architecture:

1. **REST API (The Manager):** A control plane to dynamically install, update, list, and delete skills. It acts as your private skill store.
2. **MCP Server (The Provider):** The execution plane that securely exposes the curated list of skills to your MCP-capable agents (n8n, Cursor, Claude Desktop, etc.).

---

## 🚀 Requirements

* [uv](https://docs.astral.sh/uv/) (Extremely fast Python package installer and resolver)
* Python 3.12+
* FastAPI
* FastMCP
* Agno

---

## 🛠️ Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/chameleonbr/skills_mcp_server.git](https://github.com/chameleonbr/skills_mcp_server.git)
   cd skills_mcp_server

2. **Configure environment:**
   ```bash
   cp env.example .env
   # Edit .env and set API_KEY and SKILLS_DIR
   ```

3. **Install dependencies:**
   ```bash
   uv sync
   ```

4. **Run the server:**
   ```bash
   uv run uvicorn main:app --reload
   ```

### Docker

```bash
docker-compose up --build
```

---

## 🧪 Running Tests

The project includes a comprehensive unit test suite covering models, routes, services, and the MCP server.

To run the tests, ensure you have the development dependencies installed, and then use `pytest`:

```bash
uv run pytest -v tests/
```

To run tests with coverage reporting:

```bash
uv run pytest --cov=. tests/
```

---

## 🗂️ Project Structure

```
skills_mcp_server/
├── main.py          # FastAPI app + FastMCP mount + lifespan
├── routes.py        # REST API routes (/skills)
├── services.py      # SkillManager (install, delete, reload, GitHub support)
├── mcp_server.py    # FastMCP server with Agno skill tools
├── models.py        # Pydantic request/response schemas
├── s3_skills.py     # S3Skills loader (sync from S3 bucket → LocalSkills)
├── skills/          # Skill folders (each must contain SKILL.md)
├── pyproject.toml
└── Dockerfile / docker-compose.yml
```

---

## 🔑 Authentication

All `/skills` routes require an `X-API-Key` header:

```bash
-H "X-API-Key: your_api_key"
```

Set `API_KEY` in your `.env` file.

---

## 📡 REST API — Control Plane

Interactive docs available at `http://localhost:8000/docs`.

### Skills Management

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/skills` | List all loaded skills |
| `GET` | `/skills/{name}` | Get full details of a skill |
| `POST` | `/skills` | Install a skill from URL or base64 zip |
| `POST` | `/skills/upload` | Install skill(s) via file upload |
| `DELETE` | `/skills/{name}` | Delete a skill |
| `DELETE` | `/skills` | Delete all skills |
| `GET` | `/skills/prompt_snippet` | Get system prompt snippet for agents (supports `?skill_list=skill1,skill2` and `?prompt_enforcement=false`) |
| `POST` | `/skills/prompt_snippet` | Inject prompt snippet into the passed JSON payload (supports `?skill_list=...` and `?prompt_enforcement=false`) |

### Health Check

```
GET /health
```

Returns `200 OK` with the number of currently loaded skills.

---

## 📥 Installing Skills

*Note: You no longer need to provide a name. The server will automatically extract the skill name from the `SKILL.md` file inside the archive. If your folder or URL contains multiple skills, they will all be installed automatically.*

### 1. File Upload (multipart)

```bash
curl -X POST http://localhost:8000/skills/upload \
  -H "X-API-Key: your_api_key" \
  -F "file=@my_skill.skill" \
  -F "overwrite=true" # optional, defaults to false
```

### 2. URL (direct zip download)

```bash
curl -X POST "http://localhost:8000/skills" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/my_skill.zip", "overwrite": true}'
```

### 3. Agent Skills Discovery RFC (Index JSON) 📖

Install multiple skills curated in a `skills_index.json` file as defined by the [Cloudflare Discovery RFC](https://github.com/cloudflare/agent-skills-discovery-rfc):

```bash
curl -X POST "http://localhost:8000/skills" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://raw.githubusercontent.com/LambdaTest/agent-skills/refs/heads/main/skills_index.json", "overwrite": true}'
```

### 3. GitHub URL 🐙

You can point directly to a **GitHub repository** or a **subdirectory** inside one:

```bash
# Entire repository (uses main branch)
curl -X POST "http://localhost:8000/skills" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/owner/repo"}'

# Specific branch
curl -X POST "http://localhost:8000/skills" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/owner/repo/tree/develop"}'

# Specific subfolder inside a repo
curl -X POST "http://localhost:8000/skills" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/anthropics/skills/tree/main/skills/skill-creator"}'
```

### 4. Base64 Zip

```bash
curl -X POST "http://localhost:8000/skills" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d "{\"zip_base64\": \"$(base64 -w0 my_skill.zip)\", \"overwrite\": true}"
```

---

## 🤖 MCP Server — Provider Plane

The MCP server is mounted at `/mcp` using the **StreamableHTTP** transport.

### MCP Endpoint

| Transport | URL |
|-----------|-----|
| StreamableHTTP | `POST /mcp` |
| SSE | `GET /mcp/sse` |

### MCP Configuration (Claude Desktop / any MCP client)

```json
{
  "mcpServers": {
    "skills": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "X-API-Key": "your_api_key"
      }
    }
  }
}
```

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `get_available_skills()` | List all loaded skills with name and description |
| `get_skill_instructions(skill_name)` | Load full instructions for a skill |
| `get_skill_reference(skill_name, reference_path)` | Read a reference document from a skill |
| `get_skill_script(skill_name, script_path, execute)` | Read or execute a script from a skill |

### Agent System Prompt Integration

To inject skill awareness into any agent, retrieve the pre-built prompt snippet. You can optionally pass `skill_list` to only include specific skills by name. By default, a strict prompt enforcement string is prepended to ensure agents use tools exactly as instructed, which can be disabled via `prompt_enforcement=false`. The prompt enforcement string is regularly refined for optimal formatting and context efficiency.

```bash
# Get snippet containing ALL installed skills (includes prompt enforcement by default)
curl -X GET http://localhost:8000/skills/prompt_snippet \
  -H "X-API-Key: your_api_key"

# Get snippet without the prompt enforcement rules
curl -X GET "http://localhost:8000/skills/prompt_snippet?prompt_enforcement=false" \
  -H "X-API-Key: your_api_key"

# Get snippet filtered to specific skills
curl -X GET "http://localhost:8000/skills/prompt_snippet?skill_list=web_browsing,yahoo_finance" \
  -H "X-API-Key: your_api_key"
```

Paste the returned XML snippet into your agent's `system_prompt`. It describes the loaded skills and how to use the MCP tools to access them.

### Low-Code Integration (n8n, Make, Custom Apps)

To simplify integrations in platforms where manipulating strings is hard, use the `POST` endpoint sending the payload as JSON and receiving the same payload with the `prompt` with the additional system instructions that you need to append to the system prompt of your agent:

```bash
curl -X POST "http://localhost:8000/skills/prompt_snippet" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Help me"}], "temperature": 0.7}'
```

Returns the original payload with `"prompt"` dynamically appended/overwritten with the system instructions:
```json
{
  "messages": [{"role": "user", "content": "Help me"}],
  "temperature": 0.7,
  "prompt": "<skills_system>...</skills_system>"
}
```

---

## 📂 Skill Structure

Each skill is a folder inside `SKILLS_DIR` with the following layout:

```
my_skill/
├── SKILL.md         # Required: frontmatter (name, description) + instructions
├── scripts/         # Optional: executable script files
│   └── run.py
└── references/      # Optional: documentation files
    └── guide.md
```

**`SKILL.md` example:**

```markdown
---
name: yahoo_finance
description: Fetch stock quotes and financial data from Yahoo Finance.
---

## Instructions

Use this skill when the user asks about stock prices or financial data...
```

---

## ⚙️ Environment Variables

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | *(required)* | Secret key for REST API and MCP authentication |
| `SKILLS_DIR` | `skills` | Local directory for skill folders (used by `local` backend) |
| `SKILLS_STORAGE` | `local` | Storage backend: `local` or `s3` |
| `ALLOW_RUN_SCRIPTS`| `false` | Whether to allow script execution via `mcp_get_script` |
| `LAZY_INSTALL_VENVS`| `false` | If `true`, defers `requirements.txt` generation/installation to the first time a script is executed. If `false`, installs dependencies immediately upon skill installation. |
| `ALLOW_GET_AVAILABLE_SKILLS`| `true` | Exposes the `get_available_skills` tool globally via FastMCP. Set to `false` to hide discovery mechanisms via tool calls. |

#### Detailed Explanation of Core Variables

- **`API_KEY`**: This is the master secret used to secure both the REST API endpoints and the FastMCP transport connection. It is mandatory for any operation.
- **`SKILLS_DIR`**: Defines the path (relative to the app root or absolute) where the skill folders are maintained. Defaults to `skills` in the local backend.
- **`SKILLS_STORAGE`**: Determines the strategy for loading skills. It can be set to `local` (reads from `SKILLS_DIR`) or `s3` (syncs skills from an AWS S3-compatible object storage).
- **`ALLOW_RUN_SCRIPTS`**: A security toggle. If set to `false` (default), the `get_skill_script` tool with `execute=True` will be rejected by the application. Setting it to `true` allows agents to effectively run python scripts defined by skills.
- **`LAZY_INSTALL_VENVS`**: Performance toggle. If `false` (default), the server blocks during skill installation to build the Python Virtual Environment and install the `requirements.txt`. If `true`, the installation is instantaneous, but the runtime will pause to install the `.venv` only when a script from the skill is executed for the first time.
- **`ALLOW_GET_AVAILABLE_SKILLS`**: Integration toggle. If `true` (default), the `get_available_skills` tool is exposed globally via FastMCP for dynamic discovery. If `false`, the tool is hidden, requiring the system prompt to explicitly define the skills or using the `/skills/prompt_snippet` REST endpoint for injection, this is useful to avoid the LLM to discover skills that are not meant to be used, requiring the developer to explicitly define the skills in the system prompt, injecting the snippet.

### S3 Storage (`SKILLS_STORAGE=s3`)

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_BUCKET` | *(required)* | S3 bucket name |
| `S3_PREFIX` | `skills/` | Key prefix acting as the remote skills root |
| `S3_CACHE_DIR` | `.s3cache` | Local directory where S3 files are cached |
| `AWS_ACCESS_KEY_ID` | — | AWS access key (or use IAM role / `~/.aws/credentials`) |
| `AWS_SECRET_ACCESS_KEY` | — | AWS secret key |
| `AWS_DEFAULT_REGION` | `us-east-1` | AWS region |
| `AWS_ENDPOINT_URL` | — | Custom endpoint for MinIO / LocalStack |

---

## ☁️ Storage Backends

### Local (default)

Skills are loaded from the `SKILLS_DIR` folder on disk.
With Docker, a named volume (`skills_data`) is used for persistence:

```bash
# .env
SKILLS_STORAGE=local
SKILLS_DIR=skills
```

The `docker-compose.yml` mounts `skills_data:/app/skills` automatically —
skills survive `docker-compose down` / `up` cycles.

### S3 / S3-compatible

Skills are synced from an S3 bucket to a local cache dir on every `reload()`.
The `S3Skills` loader (`s3_skills.py`) follows the same `SkillLoader` interface as Agno's `LocalSkills`.

```bash
# .env
SKILLS_STORAGE=s3
S3_BUCKET=my-bucket
S3_PREFIX=skills/
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1

# MinIO / LocalStack:
# AWS_ENDPOINT_URL=http://localhost:9000
```

Expected bucket layout:
```
my-bucket/
└── skills/
    ├── my_skill/
    │   ├── SKILL.md
    │   ├── scripts/run.py
    │   └── references/guide.md
    └── another_skill/
        └── SKILL.md
```
