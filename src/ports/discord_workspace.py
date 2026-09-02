"""Port defining the interface for Task Discord Workspaces and Thread Lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import discord

from src.domain.models import Project, Task, TaskHistory

TaskControlPanel = Literal["quick_controls", "dependencies", "history"]


@dataclass(frozen=True, slots=True)
class TaskWorkspaceRef:
    """References to a provisioned Discord Thread Workspace."""

    thread_id: int
    message_id: int
    channel_id: int
    jump_url: str


@runtime_checkable
class ITaskDiscordWorkspace(Protocol):
    """Deep Interface for managing a Task's Discord presence, Thread Workspace, and lifecycle.

    Invariants:
      - 1:1 Workspace Mapping: Every provisioned Task workspace corresponds to exactly
        one parent Forum Channel or Text Channel thread containing one root Task Action Card.
      - Tag Boundary: Forum Channel tags applied to a thread workspace never exceed Discord's
        5-tag limit and preserve existing non-managed custom tags.
      - Archive Invariant: Closed or archived tasks are guaranteed to remain archived after
        any background event or interaction update, preventing sidebar channel pollution.
      - Thread Unarchive Safety: Updates to archived threads never throw Discord HTTP errors;
        the implementation guarantees safe temporary unarchival and state restoration.
    """

    async def provision_workspace(
        self,
        task: Task,
        *,
        project: Project | None = None,
        target_container: discord.abc.GuildChannel | discord.Thread | int | None = None,
        preferred_channel_id: int | None = None,
    ) -> TaskWorkspaceRef:
        """Provisions a new Discord Thread Workspace and mounts the Task Action Card.

        Handles container resolution (Forum Channel vs Text Channel), thread creation
        with 7-day auto-archive, starter card embed rendering, interactive Task Action Card
        view mounting, and dynamic Forum Tag application.

        Args:
            task: The domain Task model to provision presence for.
            project: Optional parent Project model for tag matching and title metadata.
            target_container: Specific channel, thread, or channel ID to post in.
            preferred_channel_id: Optional fallback channel ID if target_container is omitted.

        Returns:
            TaskWorkspaceRef containing thread_id, message_id, channel_id, and jump_url.
        """
        ...

    async def sync_workspace(
        self,
        task: Task,
        *,
        project: Project | None = None,
        project_name: str | None = None,
        sync_title: bool = False,
        sync_tags: bool = True,
        sync_archive: bool = True,
        sync_starter_card: bool = True,
    ) -> bool:
        """Synchronizes an existing Thread Workspace with the current Task domain model state.

        Idempotently updates the root Task Action Card embed, resolves and refreshes
        Forum Channel tags, updates thread title (if renamed), and adjusts thread archive
        state (auto-archiving completed/archived tasks or unarchiving reopened ones).

        Args:
            task: The updated Task domain model.
            project: Optional parent Project model.
            project_name: Optional project name override for embed and tag resolution.
            sync_title: Whether to check and update thread name if the task title changed.
            sync_tags: Whether to update applied Forum Channel tags.
            sync_archive: Whether to synchronize thread archive state based on task status.
            sync_starter_card: Whether to re-render and edit the root starter message embed.

        Returns:
            True if synchronization succeeded or was a no-op; False if thread was missing.
        """
        ...

    async def refresh_action_card(
        self,
        interaction: discord.Interaction,
        task: Task,
        *,
        project: Project | None = None,
        project_name: str | None = None,
    ) -> None:
        """Refreshes the interactive Task Action Card in response to a Discord component interaction.

        Updates the interaction message with the latest Task status buttons, metadata
        embed, and thread workspace content while managing transient unarchive state.

        Args:
            interaction: The incoming button/select component interaction.
            task: The freshly mutated Task domain model.
            project: Optional parent Project model.
            project_name: Optional project name for embed display.
        """
        ...

    async def post_activity(
        self,
        task: Task,
        content: str,
        *,
        embed: discord.Embed | None = None,
        rearchive_if_completed: bool = True,
    ) -> discord.Message | None:
        """Posts an activity update, note, or Outbox Event notification into the Task's Thread Workspace.

        Safely handles transient thread unarchiving before posting and guarantees that
        completed or archived tasks are re-archived immediately after message delivery.

        Args:
            task: The Task domain model whose Thread Workspace will receive the message.
            content: Markdown content or mention text to post.
            embed: Optional rich notification embed.
            rearchive_if_completed: If True (default), ensures the thread is re-archived
                if the task is completed or archived.

        Returns:
            The created discord.Message, or None if the thread could not be reached.
        """
        ...

    async def render_task_controls(
        self,
        interaction: discord.Interaction,
        task: Task,
        *,
        panel: TaskControlPanel = "quick_controls",
        prerequisites: list[Task] | None = None,
        dependents: list[Task] | None = None,
        history: list[TaskHistory] | None = None,
        sibling_tasks: list[Task] | None = None,
    ) -> None:
        """Renders interactive ephemeral control panels (Quick Controls, Dependencies, Audit Trail).

        Args:
            interaction: The incoming button interaction.
            task: The target Task domain model.
            panel: Panel type ('quick_controls', 'dependencies', or 'history').
            prerequisites: Prerequisite tasks (for dependencies panel).
            dependents: Dependent tasks (for dependencies panel).
            history: Audit history entries (for history panel).
            sibling_tasks: Sibling project tasks (for dependency selector dropdown).
        """
        ...
