
# 🛠️ Skills MCP Server

![Python](https://img.shields.io/badge/Python-3.13%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.135%2B-green)
![FastMCP](https://img.shields.io/badge/FastMCP-3.1%2B-orange)
![Agno](https://img.shields.io/badge/Agno-Agent_Skills-blueviolet)

A centralized, sandboxed Model Context Protocol (MCP) server for managing and executing agent skills. Built with FastAPI and FastMCP, this server provides a secure environment to run dynamic skills using the **Agno framework**, which natively supports advanced *agent skills*.

## 💡 Concept

The `skills_mcp_server` acts as a dual-interface system:
1. **REST API (Manager):** A control plane to dynamically install, update, list, and delete skills.
2. **MCP Server (Provider):** The execution plane that exposes these skills to MCP-capable agents.

### Core Features
* **🔒 Sandboxed Execution:** Skills run in an isolated environment, ensuring third-party skills do not compromise the host system.
* **🧠 Agno Integration:** Leverages the Agno framework to provide rich, fully-fledged agent skills to your AI models.
* **📦 Dynamic Installation:** Install new skills at runtime via `.zip` upload, direct download URL, or a **GitHub repository URL**.
* **🐙 GitHub Support:** Point to any GitHub repo or subdirectory and the server downloads and installs the skill automatically.
* **☁️ S3 Storage:** Optionally store and load skills from an S3-compatible bucket (AWS S3, MinIO, LocalStack) via `SKILLS_STORAGE=s3`.
* **🔑 Secured Access:** API Key authentication (`X-API-Key` header) protects **all** routes including the MCP endpoint.
* **📡 MCP + REST:** A single process serves both the REST control plane and the MCP endpoint (`/mcp`).

---

## 🚀 Requirements

* [uv](https://docs.astral.sh/uv/) (Extremely fast Python package manager)
* Python 3.13+
* FastAPI, FastMCP, Agno (installed via `uv sync`)

---

## 🛠️ Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/skills_mcp_server.git
   cd skills_mcp_server
   ```

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
| `POST` | `/skills/upload` | Install a skill via file upload |
| `DELETE` | `/skills/{name}` | Delete a skill |
| `GET` | `/skills/prompt_snippet` | Get system prompt snippet for agents |

### Health Check

```
GET /health
```

Returns `200 OK` with the number of currently loaded skills.

---

## 📥 Installing Skills

*Note: You no longer need to provide a name. The server will automatically extract the skill name from the `SKILL.md` file inside the archive.*

### 1. File Upload (multipart)

```bash
curl -X POST http://localhost:8000/skills/upload \
  -H "X-API-Key: your_api_key" \
  -F "file=@my_skill.zip"
```

### 2. URL (direct zip download)

```bash
curl -X POST "http://localhost:8000/skills" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/my_skill.zip"}'
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
  -d "{\"zip_base64\": \"$(base64 -w0 my_skill.zip)\"}"
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

To inject skill awareness into any agent, retrieve the pre-built prompt snippet:

```bash
curl -X GET http://localhost:8000/skills/prompt_snippet \
  -H "X-API-Key: your_api_key"
```

Paste the returned XML snippet into your agent's `system_prompt`. It describes all loaded skills and how to use the MCP tools to access them.

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
