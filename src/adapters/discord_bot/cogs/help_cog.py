import discord
from discord import app_commands
from discord.ext import commands

from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService


class HelpCog(commands.Cog):
    """User and administrator guidance and Master Control Hub for dgg-pm."""

    def __init__(
        self,
        bot: commands.Bot,
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService,
    ):
        self.bot = bot
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service

    @app_commands.command(name="pm-menu", description="Open the Master Project Management Control Hub.")
    async def pm_menu(self, interaction: discord.Interaction) -> None:
        from src.adapters.discord_bot.views.hub_menu import PmHubView, build_hub_welcome_embed

        embed = build_hub_welcome_embed()
        view = PmHubView(self.project_service, self.team_service, self.task_service)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="help-pm", description="Display command guides and operational documentation.")
    async def help_pm(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="📖 Discord-Native Task Management (`dgg-pm`)",
            description=(
                "A zero-signup, native project management engine inside Discord.\n"
                "Data structures comply with **RFC 5545 (VTODO)** and **Microsoft Graph** schemas."
            ),
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="🎛️ Control Center Dashboards *(Zero-Typing Management)*",
            value=(
                "`/pm-menu` - Master PM Hub with tabbed navigation\n"
                "`/project-menu` - Project Management Control Center\n"
                "`/team-menu` - Team & Roster Control Center\n"
                "`/task-menu` - Task Operations & Filter Board\n"
                "`/my-settings` - Configure personal notifications (DM vs Channel Ping)"
            ),
            inline=False,
        )

        embed.add_field(
            name="📁 Project Management *(Requires Manage Server)*",
            value=(
                "`/project-create` - Instantiate a project container bound to a Forum or Text channel\n"
                "`/project-setup-forum` - Configure standard PM tags on a Discord Forum Channel\n"
                "`/project-assign` - Map a functional team to a project\n"
                "`/project-list` - View all active server projects\n"
                "`/project-archive` - Archive a project and its active tasks\n"
                "`/project-unarchive` - Restore an archived project"
            ),
            inline=False,
        )

        embed.add_field(
            name="👥 Team Management *(Requires Manage Server)*",
            value=(
                "`/team-create` - Define a team mapped to a Discord role\n"
                "`/team-assign` - Assign a user to a team (with lead/member role)\n"
                "`/team-list` - List all configured server teams"
            ),
            inline=False,
        )

        embed.add_field(
            name="⚡ Task Operations *(All Team Members)*",
            value=(
                "`/task-create` - Create project task (routed to project Forum post or Text thread)\n"
                "`/task-standalone` - Create ad-hoc, one-off task in current channel\n"
                "`/task-refresh` - Post/refresh live interactive task card in thread/channel\n"
                "`/task-status` - Update execution progress (with autocomplete)\n"
                "`/task-assign` - Assign or unassign task member\n"
                "`/task-watchers` - Add, remove, or clear watchers (CC)\n"
                "`/task-history` - View complete audit trail of status changes\n"
                "`/task-list` - Browse active tasks with interactive pagination & filters\n"
                "`/task-archive` / `/task-unarchive` - Soft-delete or restore tasks"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎛️ Interactive Embed Controls",
            value=(
                "• **`🟡 In Progress`** / **`🟢 Complete`**: Instantly update execution state\n"
                "• **`📝 Add Note`**: Log progress updates and blockers to the task thread\n"
                "• **`✏️ Edit Details`**: Edit title, description, and due date\n"
                "• **`🚫 Unassign`**: 1-click unassign from task\n"
                "• **`⚡ Priority Menu`**: 1-click priority adjustments (`High`, `Normal`, `Low`)\n"
                "• **`👤 Assignee Menu`**: Reassign team members directly from the card\n"
                "• **`📅 Due Date Menu`**: 1-click presets (`Today`, `Tomorrow`, `3 Days`, `1 Week`, etc.)\n"
                "• **`👀 Watchers Menu`**: Multi-select picker to manage watchers (CC)"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
