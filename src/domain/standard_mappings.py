from datetime import UTC, datetime
from typing import Any

from src.domain.models import Task


def to_rfc5545_vtodo(task: Task) -> str:
    """Serializes a domain Task into an RFC 5545 VTODO component string."""
    now_utc = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VTODO",
        f"UID:{task.id}",
        f"DTSTAMP:{now_utc}",
        f"SUMMARY:{task.title}",
        f"STATUS:{task.status.rfc5545_status}",
        f"PRIORITY:{task.priority.rfc5545_priority}",
        f"ORGANIZER;CN=Discord:mailto:{task.creator_discord_id}@discord.local",
    ]

    if task.body:
        # Escape newlines for RFC 5545
        escaped_body = task.body.replace("\n", "\\n")
        lines.append(f"DESCRIPTION:{escaped_body}")

    if task.due_at:
        due_str = task.due_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        lines.append(f"DUE:{due_str}")

    if task.completed_at:
        completed_str = task.completed_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        lines.append(f"COMPLETED:{completed_str}")

    if task.assignee_discord_id:
        lines.append(f"ATTENDEE;ROLE=REQ-PARTICIPANT;CN=Assignee:mailto:{task.assignee_discord_id}@discord.local")

    for watcher_id in task.watchers:
        lines.append(f"ATTENDEE;ROLE=NON-PARTICIPANT;CN=Watcher:mailto:{watcher_id}@discord.local")

    # Custom extensions for Discord metadata
    lines.append(f"X-DISCORD-GUILD-ID:{task.guild_id}")
    lines.append(f"X-DISCORD-SHORT-ID:{task.short_id}")
    if task.project_id:
        lines.append(f"X-DISCORD-PROJECT-ID:{task.project_id}")

    lines.append("END:VTODO")
    return "\r\n".join(lines)


def to_ms_graph_todo_task(task: Task) -> dict[str, Any]:
    """Serializes a domain Task into Microsoft Graph todoTask JSON schema."""
    graph_data: dict[str, Any] = {
        "id": str(task.id),
        "title": task.title,
        "status": task.status.value,
        "importance": task.priority.value,
        "isReminderOn": bool(task.due_at),
        "createdDateTime": task.created_at.astimezone(UTC).isoformat(),
        "lastModifiedDateTime": task.updated_at.astimezone(UTC).isoformat(),
        "body": {
            "content": task.body or "",
            "contentType": "text",
        },
        "extensions": [
            {
                "id": "discordMetadata",
                "guildId": str(task.guild_id),
                "shortId": task.short_id,
                "projectId": str(task.project_id) if task.project_id else None,
                "creatorDiscordId": str(task.creator_discord_id),
                "assigneeDiscordId": str(task.assignee_discord_id) if task.assignee_discord_id else None,
                "watchers": [str(w) for w in task.watchers],
            }
        ],
    }

    if task.due_at:
        graph_data["dueDateTime"] = {
            "dateTime": task.due_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC",
        }

    if task.completed_at:
        graph_data["completedDateTime"] = {
            "dateTime": task.completed_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC",
        }

    return graph_data
