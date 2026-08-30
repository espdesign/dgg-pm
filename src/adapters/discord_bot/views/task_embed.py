from datetime import UTC

import discord

from src.domain.enums import PriorityLevel, TaskStatus
from src.domain.models import Task, TaskHistory

STATUS_COLORS = {
    TaskStatus.NOT_STARTED: discord.Color.blue(),
    TaskStatus.IN_PROGRESS: discord.Color.gold(),
    TaskStatus.COMPLETED: discord.Color.green(),
}

STATUS_EMOJIS = {
    TaskStatus.NOT_STARTED: "⚪ Not Started",
    TaskStatus.IN_PROGRESS: "🟡 In Progress",
    TaskStatus.COMPLETED: "🟢 Completed",
}

PRIORITY_EMOJIS = {
    PriorityLevel.HIGH: "🔴 High",
    PriorityLevel.NORMAL: "🔵 Normal",
    PriorityLevel.LOW: "⚪ Low",
}


def build_task_embed(task: Task, project_name: str | None = None) -> discord.Embed:
    """Builds a rich, beautifully styled Discord Embed representing a task."""
    color = discord.Color.light_grey() if task.is_archived else STATUS_COLORS.get(task.status, discord.Color.blue())

    prefix_title = f"[{task.short_id}] {task.title}"
    if task.is_archived:
        prefix_title = f"📁 [ARCHIVED] {prefix_title}"

    embed = discord.Embed(
        title=prefix_title,
        description=task.body or "*No additional description provided.*",
        color=color,
        timestamp=task.created_at,
    )

    # Status and Priority row
    embed.add_field(name="Status", value=STATUS_EMOJIS.get(task.status, task.status.value), inline=True)
    embed.add_field(name="Priority", value=PRIORITY_EMOJIS.get(task.priority, task.priority.value), inline=True)

    # Project
    proj_display = project_name or (str(task.project_id) if task.project_id else "Standalone Task")
    embed.add_field(name="Project", value=proj_display, inline=True)

    # Assignee
    assignee_val = f"<@{task.assignee_discord_id}>" if task.assignee_discord_id else "*Unassigned*"
    embed.add_field(name="Assignee", value=assignee_val, inline=True)

    # Creator
    embed.add_field(name="Created By", value=f"<@{task.creator_discord_id}>", inline=True)

    # Due Date
    if task.due_at:
        due_ts = int(task.due_at.astimezone(UTC).timestamp())
        due_str = f"<t:{due_ts}:f> (<t:{due_ts}:R>)"
    else:
        due_str = "*No deadline set*"
    embed.add_field(name="Due Date", value=due_str, inline=True)

    # Watchers / CC
    if task.watchers:
        watchers_str = ", ".join(f"<@{uid}>" for uid in task.watchers)
        embed.add_field(name="Watchers (CC)", value=watchers_str, inline=False)

    footer_text = f"v{task.version} • UUID: {task.id}"
    embed.set_footer(text=footer_text)
    return embed


def build_task_history_embed(task: Task, history: list[TaskHistory]) -> discord.Embed:
    """Builds an embed listing the chronological audit history of a task."""
    embed = discord.Embed(
        title=f"📜 Audit Trail: [{task.short_id}] {task.title}",
        color=discord.Color.dark_grey(),
    )
    if not history:
        embed.description = "*No history recorded for this task.*"
        return embed

    lines = []
    for h in history:
        ts = int(h.created_at.astimezone(UTC).timestamp())
        actor = f"<@{h.actor_discord_id}>"
        time_str = f"<t:{ts}:R>"

        detail = ""
        if h.old_status and h.new_status:
            detail = f" transitioned from `{h.old_status.value}` ➔ `{h.new_status.value}`"
        elif h.action:
            detail = f" performed `{h.action.value}`"

        if h.notes:
            detail += f'\n  💬 *"{h.notes}"*'

        lines.append(f"• **{time_str}** by {actor}:{detail}")

    embed.description = "\n\n".join(lines)
    return embed
