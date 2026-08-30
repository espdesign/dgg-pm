# dgg-pm: Discord-Native Task Management Platform

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Architecture: Hexagonal](https://img.shields.io/badge/architecture-hexagonal-green.svg)](#architecture)
[![Schema: RFC 5545 & MS Graph](https://img.shields.io/badge/schema-RFC%205545%20%2F%20MS%20Graph-orange.svg)](#data-standardization)

A self-hosted, zero-signup Discord-native project management platform built to eliminate context-switching by embedding task workflows directly into Discord text channels, threads, and direct messages.

---

## Key Features

- **Discord-First Execution**: Full task lifecycle management via Discord slash commands (`/task-create`, `/task-status`, `/task-list`) and interactive message buttons (`[ 🟡 In Progress ]`, `[ 🟢 Complete ]`, `[ 📝 Add Note ]`).
- **Dedicated Project Channels & Discussion Threads**: Tasks post to project channels and automatically spawn dedicated message-attached threads (`[INF-1] Deploy API Gateway`) to keep conversation focused.
- **Human-Friendly Short IDs & Autocomplete**: Sequential project-prefixed IDs (e.g. `INF-1`, `PRJ-42`) with atomic SQL counter generation and channel-scoped autocomplete.
- **Audit History & Optimistic Concurrency Control (CAS)**: Complete lifecycle history in `task_history` table and version-checked updates preventing lost update races.
- **Postgres-Native Transactional Outbox**: At-least-once reminder and notification dispatch with `FOR UPDATE SKIP LOCKED`, unique `idempotency_key` deduplication, and dynamic Discord 429 `Retry-After` backoff.
- **RFC 5545 & Microsoft Graph Schema Portability**: Native mapping to `VTODO` and `todoTask` data standards from Day 1 for future calendar integration.
- **Discord Permission Model**: Server administration commands gated by `Manage Server` / `Administrator`, with team memberships synced to live Discord server roles.

---

## System Architecture

```
+-----------------------------------------------------------------------------------+
|                                DRIVING ADAPTERS                                   |
|                                                                                   |
|   +------------------------------------+   +----------------------------------+   |
|   |       Discord Bot Adapter          |   |        FastAPI Service Engine    |   |
|   |  (discord.py: Slash / UI / Modals) |   |    (/healthz, /metrics, schemas) |   |
|   +-----------------+------------------+   +----------------+-----------------+   |
+---------------------|---------------------------------------|---------------------+
                      |                                       |
                      v                                       v
+-----------------------------------------------------------------------------------+
|                            APPLICATION / USE CASE LAYER                           |
|                                                                                   |
|   - TaskService: CreateTask, UpdateStatus (CAS), AddNote, FilterTasks, Autocomplete|
|   - ProjectService: CreateProject, BindChannel, GenerateShortId, Archive/Restore   |
|   - TeamService: CreateTeam, SyncDiscordRoles                                     |
|   - OutboxService: EnqueueEvent, ScheduleTieredReminders, CancelTaskReminders     |
+-------------------------------------+---------------------------------------------+
                                      |
                                      v
+-----------------------------------------------------------------------------------+
|                              DOMAIN MODEL (CORE)                                  |
|                                                                                   |
|   - Entities: Task, TaskHistory, Project, Team, OutboxEvent                       |
|   - Value Objects: TaskStatus, PriorityLevel, ShortTaskId, IsoTimestamp            |
|   - State Machine: notStarted -> inProgress -> completed (with CAS validation)    |
|   - Schema Standard Mappings: RFC 5545 (VTODO) / MS Graph (todoTask)              |
+-------------------------------------+---------------------------------------------+
                                      |
                                      v
+-----------------------------------------------------------------------------------+
|                                DRIVEN ADAPTERS                                    |
|                                                                                   |
|   +------------------------------------+   +----------------------------------+   |
|   |    PostgreSQL Relational Repo      |   |  Transactional Outbox Dispatcher |   |
|   |   (SQLAlchemy Async + Alembic)     |   |   (Async Worker SKIP LOCKED)     |   |
|   +------------------------------------+   +----------------------------------+   |
+-----------------------------------------------------------------------------------+
```

---

## Discord Slash Commands

| Slash Command | Required Permission | Description |
| :--- | :--- | :--- |
| `/project-create` | `Manage Server` | Instantiate a top-level project container and bind channel |
| `/project-assign` | `Manage Server` | Map a functional team to a project with timeline |
| `/project-list` | Standard Member | List all active projects in the server |
| `/project-archive` | `Manage Server` | Archive project and its active tasks |
| `/project-unarchive`| `Manage Server` | Restore archived project |
| `/team-create` | `Manage Server` | Define a functional team mapped to a Discord server role |
| `/team-assign` | `Manage Server` | Assign a member to a team with domain role (`lead` / `member`) |
| `/team-list` | Standard Member | List all configured server teams |
| `/task-create` | Standard Member | Create project task with embed card and discussion thread |
| `/task-standalone`| Standard Member | Create ad-hoc task independent of project containers |
| `/task-status` | Standard Member | Update execution status (with autocomplete) |
| `/task-history` | Standard Member | View full chronological audit trail of a task |
| `/task-list` | Standard Member | Filter and browse active tasks with interactive pagination |
| `/task-archive` | Standard Member | Soft-delete an individual task |
| `/task-unarchive` | Standard Member | Restore an archived task |
| `/help-pm` | Standard Member | Display bot guides and operational documentation |

---

## Quickstart & Setup

### 1. Prerequisites
- Python 3.12+
- PostgreSQL 16+ (or Docker)
- Discord Bot Application Token ([Discord Developer Portal](https://discord.com/developers/applications))

### 2. Environment Configuration
Copy `.env.example` to `.env` and fill in your Discord Bot credentials:
```bash
cp .env.example .env
```
Edit `.env`:
```env
DISCORD_BOT_TOKEN=your_token_here
DISCORD_CLIENT_ID=your_client_id_here
DISCORD_GUILD_ID=your_test_guild_id   # Optional: faster command syncing in dev
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/dgg_pm
```

### 3. Required Discord Bot Permissions & Intents
When inviting the bot to your Discord server, ensure the following permissions are granted:
- **Bot Permissions:** `Manage Channels` (for auto-tagging Forum channels), `Manage Threads`, `View Channels`, `Send Messages`, `Send Messages in Threads`, `Create Public Threads`, `Manage Messages`, `Embed Links`, `Read Message History`.
- **Privileged Gateway Intents:** `Guilds`, `GuildMembers`. *(Note: `MessageContent` is explicitly **NOT** required).*

### 4. Running with Docker Compose
```bash
docker-compose up --build
```

### 5. Running with devenv (Nix)
With [`devenv`](https://devenv.sh/) installed:
```bash
# Enter the devenv developer shell (installs Python 3.12, dependencies via uv, PostgreSQL 16, tools)
devenv shell

# Start background services (PostgreSQL & app)
devenv up

# Run helper scripts inside the devenv shell
run-tests    # Execute pytest test suite
run-app      # Launch platform
db-shell     # Connect to local PostgreSQL
format       # Autoformat with ruff
lint         # Lint check with ruff
```

### 6. Running Locally (Standard Python)
```bash
pip install -e ".[dev]"
pytest
python src/main.py
```
