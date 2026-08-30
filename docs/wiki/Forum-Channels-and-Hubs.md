# 📌 Forum Channels & Interactive Hubs

Discord Forum Channels provide an ideal workspace for task management. DGG-PM automatically configures tags, pins an interactive control hub, and creates structured thread posts for every task.

---

## 🏷️ Standard Forum Tags Provisioning

When a project is bound to a `discord.ForumChannel` (or via `/pm project setup-forum`), the bot automatically configures standard project management tags up to Discord's 20-tag limit while preserving custom existing tags:

| Category | Standard Tags | Purpose |
| :--- | :--- | :--- |
| **Status** | `⏳ Not Started`, `🟡 In Progress`, `✅ Completed` | Matches and syncs with the task's execution state. |
| **Priority** | `🔴 High Priority`, `🟡 Normal Priority`, `🟢 Low Priority` | Visual urgency indicator. |
| **Assignment** | `👤 Unassigned` | Automatically applied when a task has no assignee; automatically removed when assigned. |
| **Issue Type** | `🐛 Bug`, `✨ Feature`, `🔧 Task` | Classification tags for team organization. |

---

## 🎛️ Pinned Control Hub (`📌 📊 Control Hub`)

In Discord Forum Channels, users cannot type slash commands at the forum root level. 

To make forum channels completely self-sufficient:
- When a project is created and linked to a forum channel, the bot automatically creates and **pins** a permanent thread post: **`📌 📊 [Project Name] • Control Hub`**.
- The post contains persistent interactive buttons:
  - **`➕ New Task`**: Opens the task creation popup modal directly.
  - **`⚡ Task Board`**: Launches a private interactive board with filters and pagination.
  - **`📁 Projects Hub`**: Launches a private project directory workspace.
  - **`👥 Teams Hub`**: Launches a private squad roster inspector.
  - **`⚙️ My Settings`**: Launches personal notification settings.
  - **`📖 Guides`**: Interactive documentation.

```
┌──────────────────────────────────────────────────────────┐
│  📌 📊 Mobile App • Control Hub (Public / Pinned)        │
│  Interactive management dashboard for Mobile App.        │
│                                                          │
│  [ ➕ New Task ] [ ⚡ Task Board ] [ 📁 Projects Hub ]   │
│  [ 👥 Teams Hub ] [ ⚙️ My Settings ] [ 📖 Guides ]       │
└──────────────────────────┬───────────────────────────────┘
                           │ (Alice clicks [ ⚡ Task Board ])
                           ▼
┌──────────────────────────────────────────────────────────┐
│  🔒 Task Board (Only visible to Alice • Ephemeral)       │
│  Interactive filters, pagination, and actions.           │
│  [ ◀ Prev ] [ Next ▶ ] [ 🔍 Filter ]                     │
└──────────────────────────────────────────────────────────┘
```

> [!TIP]
> **Zero Public Disruption**: All button interactions from the pinned hub respond **ephemerally** or open popup modals. The public pinned post remains pristine and is never altered or replaced when individual members interact with it.

---

## 🗂️ Task Action Cards & Workspace Threads

Every task created in a forum channel gets its own dedicated thread post:
1. **Title**: `[MOB-1] Implement OAuth login`
2. **Tags**: Automatically matches status and priority tags (e.g. `🟡 In Progress`, `🔴 High Priority`).
3. **Embed Card**: Complete markdown description, assignee, due date, short ID, and watchers.
4. **Interactive Action Card**:
   - `[ ⏳ To Do ]` `[ 🟡 In Progress ]` `[ 🟢 Complete ]`
   - `[ ⚡ Priority Dropdown ]`
   - `[ 👤 Reassign Member Select Menu ]`
   - `[ 📅 Quick Due Date Preset Picker ]`
   - `[ 📝 Add Note ]` `[ ✏️ Edit Details ]`

Updating any button instantly updates the database, updates the card embed, and synchronizes the forum tags without reloading or command typing.
