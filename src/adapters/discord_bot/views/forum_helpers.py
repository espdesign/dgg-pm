from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from src.domain.enums import PriorityLevel, TaskStatus

if TYPE_CHECKING:
    from src.domain.models import Task

logger = logging.getLogger("dgg_pm.views.forum_helpers")


STATUS_KEYWORDS = {
    TaskStatus.NOT_STARTED: ["not started", "to do", "todo", "backlog", "open"],
    TaskStatus.IN_PROGRESS: ["in progress", "doing", "active", "wip", "in-progress"],
    TaskStatus.COMPLETED: ["completed", "done", "closed", "resolved", "complete"],
}

PRIORITY_KEYWORDS = {
    PriorityLevel.HIGH: ["high", "urgent", "critical", "p0", "p1", "high priority", "p:high"],
    PriorityLevel.NORMAL: ["normal", "medium", "p2", "normal priority", "p:normal"],
    PriorityLevel.LOW: ["low", "minor", "p3", "low priority", "p:low"],
}

UNASSIGNED_KEYWORDS = ["unassigned", "not assigned", "un-assigned", "no assignee", "needs assignee"]

STANDARD_PM_TAG_DEFINITIONS = [
    {"name": "Not Started", "emoji": "⏳", "keywords": ["not started", "to do", "todo", "backlog", "open"]},
    {"name": "In Progress", "emoji": "🟡", "keywords": ["in progress", "doing", "active", "wip", "in-progress"]},
    {"name": "Completed", "emoji": "✅", "keywords": ["completed", "done", "closed", "resolved", "complete"]},
    {
        "name": "High Priority",
        "emoji": "🔴",
        "keywords": ["high", "urgent", "critical", "p0", "p1", "high priority", "p:high"],
    },
    {"name": "Normal Priority", "emoji": "🟡", "keywords": ["normal", "medium", "p2", "normal priority", "p:normal"]},
    {"name": "Low Priority", "emoji": "🟢", "keywords": ["low", "minor", "p3", "low priority", "p:low"]},
    {
        "name": "Unassigned",
        "emoji": "👤",
        "keywords": UNASSIGNED_KEYWORDS,
    },
    {"name": "Bug", "emoji": "🐛", "keywords": ["bug", "defect", "fix", "issue"]},
    {"name": "Feature", "emoji": "✨", "keywords": ["feature", "feat", "enhancement"]},
    {"name": "Task", "emoji": "🔧", "keywords": ["task", "chore", "infra"]},
]


def _matches_keyword(tag_name: str, keywords: list[str]) -> bool:
    """Checks if a tag name matches any of the target keywords (ignoring emojis/brackets/case)."""
    clean_name = tag_name.lower().replace("[", "").replace("]", "").replace(":", " ").strip()
    words = clean_name.split()
    for kw in keywords:
        if kw == clean_name or kw in words:
            return True
    return False


def resolve_forum_tags(
    forum_channel: discord.ForumChannel,
    task: Task | None = None,
    *,
    status: TaskStatus | None = None,
    priority: PriorityLevel | None = None,
    is_unassigned: bool | None = None,
    existing_tags: list[discord.ForumTag] | None = None,
) -> list[discord.ForumTag]:
    """Finds matching ForumTag objects for a task's status, priority, and unassigned state.

    Preserves any non-status/priority/unassigned custom tags already applied on the thread
    (up to Discord's maximum limit of 5 applied tags per thread).
    """
    if not hasattr(forum_channel, "available_tags") or not forum_channel.available_tags:
        return []

    if task is not None:
        status = status or task.status
        priority = priority or task.priority
        if is_unassigned is None:
            is_unassigned = task.assignee_discord_id is None

    target_status = status or TaskStatus.NOT_STARTED
    target_priority = priority or PriorityLevel.NORMAL
    unassigned_flag = bool(is_unassigned)

    available = forum_channel.available_tags
    applied: list[discord.ForumTag] = []

    # 1. Match status tag
    status_kws = STATUS_KEYWORDS.get(target_status, [])
    for tag in available:
        if _matches_keyword(tag.name, status_kws):
            applied.append(tag)
            break

    # 2. Match priority tag
    prio_kws = PRIORITY_KEYWORDS.get(target_priority, [])
    for tag in available:
        if _matches_keyword(tag.name, prio_kws):
            if tag not in applied:
                applied.append(tag)
            break

    # 3. Match Unassigned tag if unassigned
    if unassigned_flag:
        for tag in available:
            if _matches_keyword(tag.name, UNASSIGNED_KEYWORDS):
                if tag not in applied:
                    applied.append(tag)
                break

    # 4. Preserve custom tags that don't represent status, priority, or unassigned state
    if existing_tags:
        all_managed_kws = [
            kw
            for kws in list(STATUS_KEYWORDS.values()) + list(PRIORITY_KEYWORDS.values()) + [UNASSIGNED_KEYWORDS]
            for kw in kws
        ]
        for tag in existing_tags:
            # If tag is not a recognized status/priority/unassigned tag and not already added
            if not _matches_keyword(tag.name, all_managed_kws):
                if tag not in applied:
                    applied.append(tag)

    return applied[:5]


async def setup_forum_tags(forum_channel: discord.ForumChannel) -> tuple[int, int, str | None]:
    """Ensures standard project management tags exist in the given ForumChannel.

    Preserves existing tags and appends missing standard PM tags up to Discord's 20-tag limit.
    Returns (tags_added_count, total_tags_count, error_message_or_None).
    """
    if not isinstance(forum_channel, discord.ForumChannel):
        return 0, 0, "Channel is not a ForumChannel"

    existing_tags = list(getattr(forum_channel, "available_tags", []) or [])
    new_tags_to_add: list[discord.ForumTag] = []

    for tag_def in STANDARD_PM_TAG_DEFINITIONS:
        # Check if an existing tag already covers this category
        already_exists = any(_matches_keyword(t.name, tag_def["keywords"]) for t in existing_tags + new_tags_to_add)
        if not already_exists:
            if len(existing_tags) + len(new_tags_to_add) < 20:
                new_tags_to_add.append(
                    discord.ForumTag(
                        name=tag_def["name"],
                        emoji=tag_def["emoji"],
                        moderated=False,
                    )
                )

    if not new_tags_to_add:
        return 0, len(existing_tags), None

    updated_tag_list = existing_tags + new_tags_to_add
    try:
        await forum_channel.edit(available_tags=updated_tag_list)
        return len(new_tags_to_add), len(updated_tag_list), None
    except discord.Forbidden:
        logger.warning(
            "Missing 'Manage Channels' permission to configure tags in forum #%s (%s)",
            getattr(forum_channel, "name", forum_channel.id),
            forum_channel.id,
        )
        return 0, len(existing_tags), "Bot lacks 'Manage Channels' permission in this forum."
    except Exception as e:
        logger.exception("Failed to update tags in forum channel %s: %s", forum_channel.id, e)
        return 0, len(existing_tags), str(e)
