import re
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from src.adapters.discord_bot.views.task_buttons import TaskActionView
from src.adapters.discord_bot.views.task_embed import (
    build_task_embed,
    build_task_history_embed,
)
from src.adapters.discord_bot.views.task_list_view import TaskListView, build_page_embed
from src.domain.enums import PriorityLevel, TaskStatus
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService
from src.utils.date_parser import parse_natural_date


def parse_datetime(dt_str: str | None) -> datetime | None:
    """Parses various standard and natural date formats into UTC datetime."""
    return parse_natural_date(dt_str)


def extract_user_ids(text: str | None) -> list[int]:
    """Extracts Discord user snowflake IDs from mentions (<@123456789>) or raw IDs."""
    if not text:
        return []
    ids = re.findall(r"\d{4,20}", text)
    return [int(uid) for uid in set(ids)]


class TaskCog(commands.Cog):
    """Slash commands for task management, tracking, and execution."""

    def __init__(
        self,
        bot: commands.Bot,
        task_service: TaskService,
        project_service: ProjectService,
        team_service: TeamService | None = None,
    ):
        self.bot = bot
        self.task_service = task_service
        self.project_service = project_service
        self.team_service = team_service

    async def task_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Channel-scoped task autocomplete."""
        if not interaction.guild:
            return []

        # Check if channel is bound to a specific project
        project = await self.project_service.get_by_channel_id(interaction.guild.id, interaction.channel_id)
        project_id = project.id if project else None

        tasks = await self.task_service.search_for_autocomplete(
            guild_id=interaction.guild.id,
            query=current,
            project_id=project_id,
            limit=25,
        )

        choices = []
        for t in tasks:
            label = f"[{t.short_id}] {t.title}"
            if len(label) > 100:
                label = label[:97] + "..."
            choices.append(app_commands.Choice(name=label, value=t.short_id))
        return choices

    async def project_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete active projects for current guild."""
        if not interaction.guild:
            return []
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        choices = [
            app_commands.Choice(name=f"{p.name} ({p.prefix})", value=p.name)
            for p in projects
            if not current or current.lower() in p.name.lower() or current.lower() in p.prefix.lower()
        ]
        return choices[:25]

    @app_commands.command(
        name="task-create", description="Create a project-anchored task with accountability and thread."
    )
    @app_commands.describe(
        project_name="Name of the project container",
        title="Clear summary of the task to be completed",
        assignee="Discord member responsible for completing the task",
        due="Deadline (e.g. 2026-04-15 or 2026-04-15 18:00 UTC)",
        priority="Task priority level",
        cc="Watcher members to notify of progress (@mentions)",
        description="Detailed requirements or instructions",
    )
    @app_commands.choices(
        priority=[
            app_commands.Choice(name="High", value="high"),
            app_commands.Choice(name="Normal", value="normal"),
            app_commands.Choice(name="Low", value="low"),
        ]
    )
    @app_commands.autocomplete(project_name=project_autocomplete)
    async def task_create(
        self,
        interaction: discord.Interaction,
        project_name: str,
        title: str,
        assignee: discord.Member | None = None,
        due: str | None = None,
        priority: str = "normal",
        cc: str | None = None,
        description: str | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Must be used inside a Discord server.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            project = await self.project_service.get_by_name(interaction.guild.id, project_name)
            if not project:
                await interaction.followup.send(f"❌ Project '{project_name}' not found.", ephemeral=True)
                return

            due_at = parse_datetime(due)
            watchers = extract_user_ids(cc)

            task = await self.task_service.create_task(
                guild_id=interaction.guild.id,
                title=title,
                creator_discord_id=interaction.user.id,
                project_id=project.id,
                assignee_discord_id=assignee.id if assignee else None,
                due_at=due_at,
                priority=PriorityLevel(priority),
                body=description,
                watchers=watchers,
            )

            # Target channel for posting
            target_channel = interaction.channel
            if project.discord_channel_id:
                chan = self.bot.get_channel(project.discord_channel_id) or await self.bot.fetch_channel(
                    project.discord_channel_id
                )
                if isinstance(chan, (discord.TextChannel, discord.Thread)):
                    target_channel = chan

            embed = build_task_embed(task, project_name=project.name)
            view = TaskActionView(
                task_id=task.id,
                current_status=task.status,
                current_priority=task.priority,
                task_service=self.task_service,
            )

            # Send root message embed
            msg = await target_channel.send(embed=embed, view=view)

            # Spawn discussion thread attached to the message
            thread = None
            try:
                if isinstance(target_channel, discord.TextChannel):
                    thread_name = f"[{task.short_id}] {task.title}"
                    if len(thread_name) > 100:
                        thread_name = thread_name[:97] + "..."
                    thread = await msg.create_thread(name=thread_name, auto_archive_duration=1440)

                    # Post initial thread message with active TaskActionView
                    thread_intro = f"📌 Task workspace created by <@{interaction.user.id}>.\n"
                    if task.assignee_discord_id:
                        thread_intro += f"Assignee: <@{task.assignee_discord_id}> "
                    if watchers:
                        thread_intro += "Watchers: " + " ".join(f"<@{uid}>" for uid in watchers)

                    thread_view = TaskActionView(
                        task_id=task.id,
                        current_status=task.status,
                        current_priority=task.priority,
                        task_service=self.task_service,
                    )
                    await thread.send(content=thread_intro.strip(), embed=embed, view=thread_view)
            except Exception:
                # Thread creation might fail if bot lacks thread permissions
                pass

            # Update DB with Discord IDs
            thread_id = thread.id if thread else None
            await self.task_service.update_discord_message_ids(task.id, msg.id, thread_id)

            if target_channel.id != interaction.channel_id:
                await interaction.followup.send(
                    f"✅ Created task **[{task.short_id}] {task.title}** in <#{target_channel.id}>"
                    + (f" with thread <#{thread.id}>" if thread else "")
                )
            else:
                await interaction.followup.send(f"✅ Created task **[{task.short_id}]** successfully!", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Failed to create task: {e}", ephemeral=True)

    @app_commands.command(name="task-assign", description="Assign or unassign a member from a task.")
    @app_commands.describe(
        task="Task identifier (search by short ID or title)",
        assignee="Discord member to assign (leave empty to unassign)",
    )
    @app_commands.autocomplete(task=task_autocomplete)
    async def task_assign(
        self,
        interaction: discord.Interaction,
        task: str,
        assignee: discord.Member | None = None,
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        try:
            task_entity = await self.task_service.get_by_short_id(interaction.guild.id, task)
            if not task_entity:
                await interaction.followup.send(f"❌ Task '{task}' not found.", ephemeral=True)
                return

            new_assignee_id = assignee.id if assignee else None
            updated_task = await self.task_service.update_assignee(
                task_id=task_entity.id,
                new_assignee_id=new_assignee_id,
                actor_discord_id=interaction.user.id,
            )

            msg = (
                f"👤 Assigned **[{updated_task.short_id}]** to <@{new_assignee_id}>."
                if new_assignee_id
                else f"👤 Unassigned **[{updated_task.short_id}]**."
            )
            embed = build_task_embed(updated_task)
            await interaction.followup.send(f"✅ {msg}", embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to update task assignee: {e}", ephemeral=True)

    @app_commands.command(name="task-watchers", description="Manage watcher members (CC) for a task.")
    @app_commands.describe(
        task="Task identifier (search by short ID or title)",
        action="Action to perform",
        member="Discord member to add or remove (defaults to yourself)",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Add Watcher", value="add"),
            app_commands.Choice(name="Remove Watcher", value="remove"),
            app_commands.Choice(name="Clear All Watchers", value="clear"),
        ]
    )
    @app_commands.autocomplete(task=task_autocomplete)
    async def task_watchers(
        self,
        interaction: discord.Interaction,
        task: str,
        action: str,
        member: discord.Member | None = None,
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        try:
            task_entity = await self.task_service.get_by_short_id(interaction.guild.id, task)
            if not task_entity:
                await interaction.followup.send(f"❌ Task '{task}' not found.", ephemeral=True)
                return

            target_user_id = member.id if member else interaction.user.id
            current_watchers = list(task_entity.watchers)

            if action == "add":
                if target_user_id not in current_watchers:
                    current_watchers.append(target_user_id)
            elif action == "remove":
                if target_user_id in current_watchers:
                    current_watchers.remove(target_user_id)
            elif action == "clear":
                current_watchers = []

            updated_task = await self.task_service.update_details(
                task_id=task_entity.id,
                actor_discord_id=interaction.user.id,
                watchers=current_watchers,
            )

            embed = build_task_embed(updated_task)
            await interaction.followup.send(f"✅ Updated watchers for **[{updated_task.short_id}]**!", embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to update watchers: {e}", ephemeral=True)

    @app_commands.command(
        name="task-refresh",
        description="Post or refresh the live interactive Task Action Card in this thread or channel.",
    )
    @app_commands.describe(
        task="Task identifier (optional if run directly inside the task's thread)",
    )
    @app_commands.autocomplete(task=task_autocomplete)
    async def task_refresh(
        self,
        interaction: discord.Interaction,
        task: str | None = None,
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        try:
            task_entity = None
            if task:
                task_entity = await self.task_service.get_by_short_id(interaction.guild.id, task)
            elif isinstance(interaction.channel, discord.Thread):
                task_entity = await self.task_service.get_by_thread_id(interaction.guild.id, interaction.channel.id)

            if not task_entity:
                await interaction.followup.send(
                    "❌ Could not find task. Please specify the `task` parameter or run inside a task thread.",
                    ephemeral=True,
                )
                return

            project_name = None
            if task_entity.project_id:
                project = await self.project_service.get_by_id(task_entity.project_id)
                if project:
                    project_name = project.name

            embed = build_task_embed(task_entity, project_name=project_name)
            view = TaskActionView(
                task_id=task_entity.id,
                current_status=task_entity.status,
                current_priority=task_entity.priority,
                task_service=self.task_service,
            )
            msg = await interaction.channel.send(embed=embed, view=view)
            # Link newest card to task
            thread_id = (
                interaction.channel.id
                if isinstance(interaction.channel, discord.Thread)
                else task_entity.discord_thread_id
            )
            await self.task_service.update_discord_message_ids(task_entity.id, msg.id, thread_id)

            await interaction.followup.send(
                f"✅ Posted updated Task Action Card for **[{task_entity.short_id}]**!",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to refresh task card: {e}", ephemeral=True)

    @app_commands.command(
        name="task-standalone", description="Instantiate an ad-hoc task independent of project containers."
    )
    @app_commands.describe(
        title="Summary of the task",
        assignee="Discord member responsible for completing the task",
        due="Deadline (e.g. 2026-04-15 or 2026-04-15 18:00 UTC)",
        priority="Priority level",
        cc="Watcher members to notify (@mentions)",
        description="Detailed requirements",
    )
    @app_commands.choices(
        priority=[
            app_commands.Choice(name="High", value="high"),
            app_commands.Choice(name="Normal", value="normal"),
            app_commands.Choice(name="Low", value="low"),
        ]
    )
    async def task_standalone(
        self,
        interaction: discord.Interaction,
        title: str,
        assignee: discord.Member | None = None,
        due: str | None = None,
        priority: str = "normal",
        cc: str | None = None,
        description: str | None = None,
    ) -> None:
        if not interaction.guild:
            return

        await interaction.response.defer()
        try:
            due_at = parse_datetime(due)
            watchers = extract_user_ids(cc)

            task = await self.task_service.create_task(
                guild_id=interaction.guild.id,
                title=title,
                creator_discord_id=interaction.user.id,
                project_id=None,
                assignee_discord_id=assignee.id if assignee else None,
                due_at=due_at,
                priority=PriorityLevel(priority),
                body=description,
                watchers=watchers,
            )

            embed = build_task_embed(task)
            view = TaskActionView(
                task_id=task.id,
                current_status=task.status,
                current_priority=task.priority,
                task_service=self.task_service,
            )
            msg = await interaction.channel.send(embed=embed, view=view)
            await self.task_service.update_discord_message_ids(task.id, msg.id, None)

            await interaction.followup.send(f"✅ Created standalone task **[{task.short_id}]**!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to create standalone task: {e}", ephemeral=True)

    @app_commands.command(name="task-status", description="Update task execution status (with autocomplete).")
    @app_commands.describe(
        task="Task identifier (search by short ID or title)",
        status="New execution status",
        notes="Optional notes explaining status change or progress",
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Not Started", value="notStarted"),
            app_commands.Choice(name="In Progress", value="inProgress"),
            app_commands.Choice(name="Completed", value="completed"),
        ]
    )
    @app_commands.autocomplete(task=task_autocomplete)
    async def task_status(
        self,
        interaction: discord.Interaction,
        task: str,
        status: str,
        notes: str | None = None,
    ) -> None:
        if not interaction.guild:
            return

        await interaction.response.defer()
        try:
            task_entity = await self.task_service.get_by_short_id(interaction.guild.id, task)
            if not task_entity:
                await interaction.followup.send(f"❌ Task '{task}' not found in this server.", ephemeral=True)
                return

            new_status = TaskStatus(status)
            updated_task = await self.task_service.update_status(
                task_id=task_entity.id,
                new_status=new_status,
                expected_version=task_entity.version,
                actor_discord_id=interaction.user.id,
                notes=notes,
            )

            embed = build_task_embed(updated_task)
            await interaction.followup.send(
                f"✅ Updated **[{updated_task.short_id}]** status to **{new_status.value}**!",
                embed=embed,
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to update status: {e}", ephemeral=True)

    @app_commands.command(name="task-history", description="View the full audit trail and status history of a task.")
    @app_commands.describe(task="Task identifier (search by short ID or title)")
    @app_commands.autocomplete(task=task_autocomplete)
    async def task_history(self, interaction: discord.Interaction, task: str) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        task_entity = await self.task_service.get_by_short_id(interaction.guild.id, task)
        if not task_entity:
            await interaction.followup.send(f"❌ Task '{task}' not found.", ephemeral=True)
            return

        history = await self.task_service.get_history(task_entity.id)
        embed = build_task_history_embed(task_entity, history)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="task-archive", description="Archive a task.")
    @app_commands.describe(task="Task identifier")
    @app_commands.autocomplete(task=task_autocomplete)
    async def task_archive(self, interaction: discord.Interaction, task: str) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        task_entity = await self.task_service.get_by_short_id(interaction.guild.id, task)
        if not task_entity:
            await interaction.followup.send(f"❌ Task '{task}' not found.", ephemeral=True)
            return

        await self.task_service.archive_task(task_entity.id, interaction.user.id)
        await interaction.followup.send(f"📁 Task **[{task_entity.short_id}] {task_entity.title}** has been archived.")

    @app_commands.command(name="task-unarchive", description="Restore an archived task.")
    @app_commands.describe(task="Task identifier")
    async def task_unarchive(self, interaction: discord.Interaction, task: str) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        task_entity = await self.task_service.get_by_short_id(interaction.guild.id, task)
        if not task_entity:
            await interaction.followup.send(f"❌ Task '{task}' not found.", ephemeral=True)
            return

        await self.task_service.unarchive_task(task_entity.id, interaction.user.id)
        await interaction.followup.send(f"📂 Task **[{task_entity.short_id}] {task_entity.title}** has been restored.")

    @app_commands.command(name="task-list", description="Display filtered active tasks with interactive pagination.")
    @app_commands.describe(
        project_name="Filter by project name",
        user="Filter by assignee",
        status="Filter by execution status",
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Not Started", value="notStarted"),
            app_commands.Choice(name="In Progress", value="inProgress"),
            app_commands.Choice(name="Completed", value="completed"),
        ]
    )
    @app_commands.autocomplete(project_name=project_autocomplete)
    async def task_list(
        self,
        interaction: discord.Interaction,
        project_name: str | None = None,
        user: discord.Member | None = None,
        status: str | None = None,
    ) -> None:
        if not interaction.guild:
            return

        await interaction.response.defer()
        try:
            project_id = None
            title_parts = []
            if project_name:
                project = await self.project_service.get_by_name(interaction.guild.id, project_name)
                if not project:
                    await interaction.followup.send(f"❌ Project '{project_name}' not found.", ephemeral=True)
                    return
                project_id = project.id
                title_parts.append(f"Project: {project.name}")

            if user:
                title_parts.append(f"Assignee: {user.display_name}")

            filter_status = TaskStatus(status) if status else None
            if filter_status:
                title_parts.append(f"Status: {filter_status.value}")

            tasks, total_count = await self.task_service.list_tasks(
                guild_id=interaction.guild.id,
                project_id=project_id,
                assignee_discord_id=user.id if user else None,
                status=filter_status,
                limit=100,
            )

            title_context = "Tasks (" + ", ".join(title_parts) + ")" if title_parts else "All Active Tasks"
            embed = build_page_embed(tasks, 0, total_count, title_context)
            view = TaskListView(tasks, total_count, title_context)

            await interaction.followup.send(embed=embed, view=view)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to list tasks: {e}", ephemeral=True)

    @app_commands.command(name="task-menu", description="Open interactive Task Operations Control Center.")
    async def task_menu(self, interaction: discord.Interaction) -> None:
        from src.adapters.discord_bot.views.task_menu import TaskMenuView, build_task_menu_embed

        embed = build_task_menu_embed()
        view = TaskMenuView(self.task_service, self.project_service, self.team_service)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
