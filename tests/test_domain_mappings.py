from datetime import UTC, datetime
from uuid import uuid4

from src.domain.enums import PriorityLevel, TaskStatus
from src.domain.models import Task
from src.domain.standard_mappings import to_ms_graph_todo_task, to_rfc5545_vtodo


def test_rfc5545_vtodo_serialization():
    task_id = uuid4()
    due = datetime(2026, 4, 15, 18, 0, 0, tzinfo=UTC)
    task = Task(
        id=task_id,
        guild_id=123456789012345678,
        short_id="INF-1",
        title="Deploy API Gateway",
        body="Deploy FastAPI with PostgreSQL.\nInclude tests.",
        status=TaskStatus.IN_PROGRESS,
        priority=PriorityLevel.HIGH,
        creator_discord_id=111222333444555666,
        assignee_discord_id=999888777666555444,
        due_at=due,
        watchers=[555666777888999000],
    )

    vtodo = to_rfc5545_vtodo(task)

    assert "BEGIN:VTODO" in vtodo
    assert f"UID:{task_id}" in vtodo
    assert "SUMMARY:Deploy API Gateway" in vtodo
    assert "STATUS:IN-PROCESS" in vtodo
    assert "PRIORITY:1" in vtodo
    assert "ORGANIZER;CN=Discord:mailto:111222333444555666@discord.local" in vtodo
    assert "ATTENDEE;ROLE=REQ-PARTICIPANT;CN=Assignee:mailto:999888777666555444@discord.local" in vtodo
    assert "ATTENDEE;ROLE=NON-PARTICIPANT;CN=Watcher:mailto:555666777888999000@discord.local" in vtodo
    assert "DUE:20260415T180000Z" in vtodo
    assert "X-DISCORD-SHORT-ID:INF-1" in vtodo
    assert "END:VTODO" in vtodo


def test_ms_graph_todo_task_serialization():
    task_id = uuid4()
    due = datetime(2026, 4, 15, 18, 0, 0, tzinfo=UTC)
    task = Task(
        id=task_id,
        guild_id=123456789012345678,
        short_id="INF-1",
        title="Deploy API Gateway",
        body="Deploy FastAPI with PostgreSQL.",
        status=TaskStatus.COMPLETED,
        priority=PriorityLevel.NORMAL,
        creator_discord_id=111222333444555666,
        assignee_discord_id=999888777666555444,
        due_at=due,
        completed_at=due,
        watchers=[555666777888999000],
    )

    graph = to_ms_graph_todo_task(task)

    assert graph["id"] == str(task_id)
    assert graph["title"] == "Deploy API Gateway"
    assert graph["status"] == "completed"
    assert graph["importance"] == "normal"
    assert graph["body"]["content"] == "Deploy FastAPI with PostgreSQL."
    assert graph["dueDateTime"]["dateTime"] == "2026-04-15T18:00:00"
    assert graph["completedDateTime"]["dateTime"] == "2026-04-15T18:00:00"

    ext = graph["extensions"][0]
    assert ext["shortId"] == "INF-1"
    assert ext["assigneeDiscordId"] == "999888777666555444"
    assert ext["watchers"] == ["555666777888999000"]
