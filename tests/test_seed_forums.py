from __future__ import annotations

from unittest.mock import MagicMock

import discord
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scripts.seed_forums import (
    check_production_safety_guard,
    seed_forums_db,
)
from src.adapters.discord_bot.views.forum_helpers import (
    STANDARD_PM_TAG_DEFINITIONS,
    resolve_forum_tags,
)
from src.config import settings
from src.domain.enums import PriorityLevel, TaskStatus


def test_seed_forums_safety_guards(monkeypatch):
    # Production environment check
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="SAFETY BLOCK: Seeding script cannot be run in production"):
        check_production_safety_guard()

    # Cloud DB check
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(
        settings, "DATABASE_URL", "postgresql+asyncpg://user:pass@ep-cool-db.us-east-2.neon.tech/dgg_pm"
    )
    with pytest.raises(
        RuntimeError, match="SAFETY BLOCK: DATABASE_URL appears to point to a production/cloud database"
    ):
        check_production_safety_guard()


@pytest.mark.asyncio
async def test_seed_forums_db_creation(async_engine):
    guild_id = 8877665544
    session_factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    results, task_service = await seed_forums_db(
        guild_id=guild_id,
        reset_existing=True,
        session_factory=session_factory,
    )

    # 1. Verify Forum 1 (Single Project)
    single_forum_name = "🎯-single-project"
    assert single_forum_name in results
    single_entries = results[single_forum_name]
    assert len(single_entries) == 1

    core_proj = single_entries[0]["project"]
    assert core_proj.name == "Platform Core"
    assert core_proj.prefix == "CORE"
    assert core_proj.category == "Core Engineering"

    core_tasks = single_entries[0]["tasks"]
    assert len(core_tasks) == 4
    assert {t.status for t in core_tasks} == {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.NOT_STARTED}
    assert {t.priority for t in core_tasks} == {PriorityLevel.HIGH, PriorityLevel.NORMAL, PriorityLevel.LOW}

    # 2. Verify Forum 2 (Three Projects)
    multi_forum_name = "🌐-multi-project-hub"
    assert multi_forum_name in results
    multi_entries = results[multi_forum_name]
    assert len(multi_entries) == 3

    multi_projects_by_prefix = {entry["project"].prefix: entry for entry in multi_entries}
    assert set(multi_projects_by_prefix.keys()) == {"WEB", "GATE", "MBL"}

    # Web Portal
    web_entry = multi_projects_by_prefix["WEB"]
    assert web_entry["project"].name == "Web Portal"
    assert len(web_entry["tasks"]) == 3
    assert any(t.status == TaskStatus.COMPLETED for t in web_entry["tasks"])
    assert any(t.status == TaskStatus.IN_PROGRESS for t in web_entry["tasks"])
    assert any(t.status == TaskStatus.NOT_STARTED for t in web_entry["tasks"])

    # API Gateway
    gate_entry = multi_projects_by_prefix["GATE"]
    assert gate_entry["project"].name == "API Gateway"
    assert len(gate_entry["tasks"]) == 3

    # Mobile App
    mbl_entry = multi_projects_by_prefix["MBL"]
    assert mbl_entry["project"].name == "Mobile App"
    assert len(mbl_entry["tasks"]) == 3

    # Total projects created across both forums = 4
    all_projects = await task_service.project_service.list_projects(guild_id)
    assert len(all_projects) == 4


@pytest.mark.asyncio
async def test_seed_forums_idempotency(async_engine):
    guild_id = 1122334455
    session_factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # First run
    await seed_forums_db(
        guild_id=guild_id,
        reset_existing=True,
        session_factory=session_factory,
    )

    # Second run without reset should not duplicate projects or tasks
    results2, task_service = await seed_forums_db(
        guild_id=guild_id,
        reset_existing=False,
        session_factory=session_factory,
    )

    all_projects = await task_service.project_service.list_projects(guild_id)
    assert len(all_projects) == 4

    total_tasks = sum(len(entry["tasks"]) for entries in results2.values() for entry in entries)
    # 4 tasks in CORE + 3 in WEB + 3 in GATE + 3 in MBL = 13 tasks total
    assert total_tasks == 13


def _create_mock_tag(tag_id: int, name: str, emoji: str | None = None) -> MagicMock:
    tag = MagicMock(spec=discord.ForumTag)
    tag.id = tag_id
    tag.name = name
    tag.emoji = emoji
    tag.moderated = False
    return tag


def test_multi_project_forum_tag_resolution():
    mock_forum = MagicMock(spec=discord.ForumChannel)
    tags = [_create_mock_tag(i + 1, d["name"], d["emoji"]) for i, d in enumerate(STANDARD_PM_TAG_DEFINITIONS)]
    # Add per-project tags
    tags.extend(
        [
            _create_mock_tag(20, "Web Portal", "📁"),
            _create_mock_tag(21, "API Gateway", "📁"),
            _create_mock_tag(22, "Mobile App", "📁"),
        ]
    )
    mock_forum.available_tags = tags

    # Test resolving tags for a Web Portal task
    web_tags = resolve_forum_tags(
        mock_forum,
        status=TaskStatus.IN_PROGRESS,
        priority=PriorityLevel.HIGH,
        project_name="Web Portal",
    )
    tag_names = {t.name for t in web_tags}
    assert "In Progress" in tag_names
    assert "High Priority" in tag_names
    assert "Web Portal" in tag_names
    assert "API Gateway" not in tag_names

    # Test resolving tags for an API Gateway task
    gate_tags = resolve_forum_tags(
        mock_forum,
        status=TaskStatus.COMPLETED,
        priority=PriorityLevel.NORMAL,
        project_name="API Gateway",
    )
    gate_tag_names = {t.name for t in gate_tags}
    assert "Completed" in gate_tag_names
    assert "Normal Priority" in gate_tag_names
    assert "API Gateway" in gate_tag_names
    assert "Web Portal" not in gate_tag_names
