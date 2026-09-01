# dgg-pm Domain Vocabulary (CONTEXT.md)

This glossary establishes the canonical domain language for `dgg-pm`. Use these terms consistently across domain models, service interfaces, database tables, and documentation.

---

### Core Entities & Actors

- **Actor**: An authenticated caller (Discord member, terminal user, or API client) requesting an operation, characterized by `user_id`, assigned `role_ids`, and server manager status (`is_admin`).
- **Project**: A top-level container for work items bound to a dedicated Discord channel or forum channel. Identified by a unique short key `prefix` (e.g. `INF`, `PRJ`), an assigned squad role, and an optional project lead.
- **Squad Role**: A Discord server role linked directly to a project container. Server members holding this role possess contributor permissions to create, assign, and update tasks within that project.
- **Project Lead**: The designated Discord member accountable for the overall execution of a project container.
- **Task**: A discrete, trackable work item with a sequential short identifier (e.g. `INF-42`), description, priority level, due timestamp, execution status, optional assignee, and watcher list.
- **Task Status**: State machine progression: `NOT_STARTED` (`notStarted`) -> `IN_PROGRESS` (`inProgress`) -> `COMPLETED` (`completed`). Tasks can be moved between states with optimistic concurrency control (version CAS).
- **Prerequisite / Dependency**: A directed prerequisite link between two tasks (`Dependent Task` requires `Prerequisite Task`). Circular dependencies are strictly forbidden.
- **Task Dependency Graph (DAG)**: A directed acyclic graph capturing all task prerequisite relationships within a project or guild, used to calculate task readiness states (`complete`, `active`, `available`, `locked`, `blocked`).

---

### Seams & Adapters

- **Application Services** (`src/services/`): Pure business logic modules (`AuthService`, `TaskService`, `ProjectService`, `TeamService`, `OutboxService`) that operate on domain entities and value objects without importing external UI or transport SDKs.
- **Driving Adapters** (`src/adapters/`): Adapters that initiate calls into application services:
  - **Discord Bot Adapter** (`src/adapters/discord_bot/`): Discord interaction handlers, slash commands (`PmCog`), action card buttons, and interactive modal forms.
  - **REST API Adapter** (`src/adapters/api/`): FastAPI endpoints for health checks, metrics, and programmatic CLI tokens.
- **Driven Adapters** (`src/adapters/`): Implementations of output ports:
  - **PostgreSQL Repository** (`src/adapters/db/`): Async SQLAlchemy relational persistence with transactional outbox event storage.
  - **Tree Renderer** (`src/adapters/rendering/`): Image generation engine drawing DAG dependency diagrams with Pillow.
  - **Discord Notifier** (`src/adapters/discord_bot/discord_notifier.py`): Dispatcher sending outbox notifications and direct messages to Discord channels/threads.
