import logging
from uuid import UUID

import discord

from src.adapters.discord_bot.views.task_buttons import TaskActionView
from src.adapters.discord_bot.views.task_embed import build_task_embed
from src.domain.enums import PriorityLevel, TaskStatus
from src.domain.models import Project
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService
from src.utils.date_parser import parse_natural_date

logger = logging.getLogger("dgg_pm.views.task_menu")


def _extract_user_ids(text: str | None) -> list[int]:
    import re

    if not text:
        return []
    ids = re.findall(r"\d{4,20}", text)
    return [int(uid) for uid in set(ids)]


class TaskCreateModal(discord.ui.Modal):
    """Modal to create a new task within a project or standalone."""

    def __init__(
        self,
        task_service: TaskService,
        project: Project | None = None,
        target_channel: discord.TextChannel | discord.Thread | None = None,
    ):
        title_str = f"New Task: {project.prefix}" if project else "New Standalone Task"
        super().__init__(title=title_str)
        self.task_service = task_service
        self.project = project
        self.target_channel = target_channel

        self.title_input = discord.ui.TextInput(
            label="Task Title",
            placeholder="e.g. Implement OAuth2 login, Database migration",
            required=True,
            max_length=100,
        )
        self.add_item(self.title_input)

        self.desc_input = discord.ui.TextInput(
            label="Description (Optional)",
            style=discord.TextStyle.paragraph,
            placeholder="Requirements, acceptance criteria, or execution notes...",
            required=False,
            max_length=1500,
        )
        self.add_item(self.desc_input)

        self.due_input = discord.ui.TextInput(
            label="Due Date (e.g. 'tomorrow', 'in 3 days')",
            placeholder="e.g. tomorrow, in 3 days, friday 5pm, 2026-04-15",
            required=False,
            max_length=60,
        )
        self.add_item(self.due_input)

        self.assignee_input = discord.ui.TextInput(
            label="Assignee (@mention or User ID)",
            placeholder="e.g. @alice or leave empty",
            required=False,
            max_length=50,
        )
        self.add_item(self.assignee_input)

        self.priority_input = discord.ui.TextInput(
            label="Priority (high / normal / low)",
            default="normal",
            placeholder="normal, high, low",
            required=False,
            max_length=20,
        )
        self.add_item(self.priority_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Must be run in a Discord server.", ephemeral=True)
            return

        title = self.title_input.value.strip()
        body = self.desc_input.value.strip() or None
        due_at = parse_natural_date(self.due_input.value.strip())

        assignee_uids = _extract_user_ids(self.assignee_input.value.strip())
        assignee_id = assignee_uids[0] if assignee_uids else None

        p_str = self.priority_input.value.strip().lower()
        priority = PriorityLevel.NORMAL
        if p_str in ("high", "h", "urgent"):
            priority = PriorityLevel.HIGH
        elif p_str in ("low", "l"):
            priority = PriorityLevel.LOW

        try:
            task = await self.task_service.create_task(
                guild_id=interaction.guild.id,
                title=title,
                creator_discord_id=interaction.user.id,
                project_id=self.project.id if self.project else None,
                assignee_discord_id=assignee_id,
                due_at=due_at,
                priority=priority,
                body=body,
            )

            target_chan = self.target_channel or interaction.channel
            embed = build_task_embed(task, project_name=self.project.name if self.project else None)
            view = TaskActionView(
                task_id=task.id,
                current_status=task.status,
                current_priority=task.priority,
                task_service=self.task_service,
            )

            msg = None
            if isinstance(target_chan, (discord.TextChannel, discord.Thread)):
                msg = await target_chan.send(embed=embed, view=view)
                if isinstance(target_chan, discord.TextChannel):
                    thread = await msg.create_thread(
                        name=f"[{task.short_id}] {task.title[:90]}",
                        auto_archive_duration=1440,
                    )
                    thread_view = TaskActionView(
                        task_id=task.id,
                        current_status=task.status,
                        current_priority=task.priority,
                        task_service=self.task_service,
                    )
                    thread_intro = f"📌 Task workspace created by <@{interaction.user.id}>."
                    if task.assignee_discord_id:
                        thread_intro += f" Assignee: <@{task.assignee_discord_id}>"
                    await thread.send(content=thread_intro, embed=embed, view=thread_view)
                    await self.task_service.update_discord_message_ids(task.id, msg.id, thread.id)
                else:
                    await self.task_service.update_discord_message_ids(task.id, msg.id, None)

            await interaction.response.send_message(
                f"✅ Created task **[{task.short_id}] {task.title}**!",
                ephemeral=True,
            )
        except Exception as e:
            logger.exception("Error creating task via modal: %s", e)
            await interaction.response.send_message(f"❌ Failed to create task: {e}", ephemeral=True)


class TaskSelectProjectView(discord.ui.View):
    """View to select which project container to create a task in."""

    def __init__(
        self,
        projects: list[Project],
        task_service: TaskService,
        project_service: ProjectService,
        team_service: TeamService | None = None,
    ):
        super().__init__(timeout=120)
        self.task_service = task_service
        self.project_service = project_service
        self.team_service = team_service
        self.projects = {str(p.id): p for p in projects}

        options = [
            discord.SelectOption(
                label=f"{p.name} ({p.prefix})",
                value=str(p.id),
                description=f"Channel: #{p.discord_channel_id}" if p.discord_channel_id else "Project Container",
                emoji="📁",
            )
            for p in projects[:25]
        ]
        self.select = discord.ui.Select(
            placeholder="📁 Select Project for Task...",
            options=options,
            row=0,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

        self.back_btn = discord.ui.Button(
            label="Back to Task Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        self.back_btn.callback = self._on_back_clicked
        self.add_item(self.back_btn)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        project_id_str = self.select.values[0]
        project = self.projects.get(project_id_str)
        if not project:
            await interaction.response.send_message("❌ Project not found.", ephemeral=True)
            return

        target_channel = None
        if project.discord_channel_id and interaction.guild:
            target_channel = interaction.guild.get_channel(project.discord_channel_id)

        modal = TaskCreateModal(self.task_service, project=project, target_channel=target_channel)
        await interaction.response.send_modal(modal)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = TaskMenuView(self.task_service, self.project_service, self.team_service)
        embed = build_task_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class TaskMenuView(discord.ui.View):
    """Control Center View for Task Operations and Live Interactive Filtering."""

    def __init__(
        self,
        task_service: TaskService,
        project_service: ProjectService,
        team_service: TeamService | None = None,
        projects: list[Project] | None = None,
    ):
        super().__init__(timeout=None)
        self.task_service = task_service
        self.project_service = project_service
        self.team_service = team_service
        self.selected_project_id: UUID | None = None
        self.selected_status: TaskStatus | None = None

        # Row 0: Action Buttons
        self.new_task_btn = discord.ui.Button(
            label="New Project Task",
            emoji="✨",
            style=discord.ButtonStyle.primary,
            row=0,
        )
        self.new_task_btn.callback = self._on_new_task_clicked
        self.add_item(self.new_task_btn)

        self.standalone_btn = discord.ui.Button(
            label="Standalone Task",
            emoji="📌",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        self.standalone_btn.callback = self._on_standalone_clicked
        self.add_item(self.standalone_btn)

        self.refresh_btn = discord.ui.Button(
            label="Refresh Board",
            emoji="🔄",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        self.refresh_btn.callback = self._on_refresh_clicked
        self.add_item(self.refresh_btn)

        if self.team_service:
            self.hub_btn = discord.ui.Button(
                label="PM Main Menu",
                emoji="🏠",
                style=discord.ButtonStyle.secondary,
                row=0,
            )
            self.hub_btn.callback = self._on_hub_clicked
            self.add_item(self.hub_btn)

        # Row 1: Status Filter Select
        status_options = [
            discord.SelectOption(label="All Statuses", value="all", emoji="📊", default=True),
            discord.SelectOption(label="In Progress", value="inProgress", emoji="🟡"),
            discord.SelectOption(label="Not Started", value="notStarted", emoji="⚪"),
            discord.SelectOption(label="Completed", value="completed", emoji="🟢"),
        ]
        self.status_select = discord.ui.Select(
            placeholder="📊 Filter by Status...",
            options=status_options,
            row=1,
        )
        self.status_select.callback = self._on_status_filter_changed
        self.add_item(self.status_select)

    async def _on_hub_clicked(self, interaction: discord.Interaction) -> None:
        from src.adapters.discord_bot.views.hub_menu import PmHubView, build_hub_welcome_embed

        if self.team_service:
            view = PmHubView(self.project_service, self.team_service, self.task_service)
            embed = build_hub_welcome_embed()
            await interaction.response.edit_message(content=None, embed=embed, view=view)

    async def _on_new_task_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        if not projects:
            await interaction.response.send_message(
                "📁 No active projects found. Use **Standalone Task** or create a project first!",
                ephemeral=True,
            )
            return
        view = TaskSelectProjectView(projects, self.task_service, self.project_service, self.team_service)
        embed = discord.Embed(
            title="📁 Select Project Container",
            description="Choose which active project to create the task inside:",
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_standalone_clicked(self, interaction: discord.Interaction) -> None:
        modal = TaskCreateModal(self.task_service, project=None, target_channel=interaction.channel)
        await interaction.response.send_modal(modal)

    async def _on_status_filter_changed(self, interaction: discord.Interaction) -> None:
        val = self.status_select.values[0]
        self.selected_status = None if val == "all" else TaskStatus(val)
        await self._render_filtered_board(interaction)

    async def _on_refresh_clicked(self, interaction: discord.Interaction) -> None:
        await self._render_filtered_board(interaction)

    async def _render_filtered_board(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return

        tasks, total = await self.task_service.list_tasks(
            guild_id=interaction.guild.id,
            project_id=self.selected_project_id,
            status=self.selected_status,
            include_archived=False,
            limit=15,
        )

        status_label = self.selected_status.value if self.selected_status else "All"
        embed = discord.Embed(
            title=f"⚡ Task Board ({total} tasks found)",
            description=f"**Filters Active**: Status: `{status_label}`",
            color=discord.Color.blurple(),
        )

        if not tasks:
            embed.add_field(name="No Tasks", value="No tasks match the active filter criteria.", inline=False)
        else:
            for t in tasks:
                icon = "🟢" if t.is_completed else ("🟡" if t.status == TaskStatus.IN_PROGRESS else "⚪")
                assignee_str = f"<@{t.assignee_discord_id}>" if t.assignee_discord_id else "Unassigned"
                due_str = f" | Due: {t.due_at.strftime('%b %d')}" if t.due_at else ""
                embed.add_field(
                    name=f"{icon} [{t.short_id}] {t.title}",
                    value=f"• Assignee: {assignee_str}{due_str}\n• Priority: `{t.priority.value.upper()}`",
                    inline=False,
                )

        await interaction.response.edit_message(embed=embed, view=self)


def build_task_menu_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚡ Task Operations Control Center",
        description=(
            "Create, filter, and track tasks across all projects with zero typing.\n\n"
            "• **`✨ New Project Task`**: Pick a project and create a new task with full thread support\n"
            "• **`📌 Standalone Task`**: Create an ad-hoc task in the current channel\n"
            "• **`📊 Filter Menu`**: Filter board in real-time by status (In Progress, Completed, Not Started)\n"
            "• **`🔄 Refresh Board`**: Reload the latest task state"
        ),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="dgg-pm • Zero-typing task operations")
    return embed
