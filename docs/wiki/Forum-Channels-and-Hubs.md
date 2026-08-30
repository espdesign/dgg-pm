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
- The post contains the interactive Master Hub View with live buttons:
  - **`⚡ Tasks Hub`**: Create tasks via modals, filter active task boards.
  - **`📁 Projects Hub`**: Switch containers, view bound channels.
  - **`👥 Teams Hub`**: View squad rosters and leads.
  - **`⚙️ My Settings`**: Change personal notification delivery preferences.
  - **`📖 Guides`**: Interactive documentation.

```
┌──────────────────────────────────────────────────────────┐
│  🎛️ Mobile App • Control Hub                             │
│  Interactive management dashboard for Mobile App.        │
│                                                          │
│  [ 📁 Projects Hub ] [ 👥 Teams Hub ] [ ⚡ Tasks Hub ]   │
│  [ ⚙️ My Settings ]   [ 📖 Guides ]                       │
└──────────────────────────────────────────────────────────┘
```

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
