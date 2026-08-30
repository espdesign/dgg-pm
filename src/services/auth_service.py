"""Role and team-based authorization service for dgg-pm."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

import discord

from src.domain.exceptions import PermissionDeniedError
from src.domain.models import Task

if TYPE_CHECKING:
    from src.services.project_service import ProjectService
    from src.services.team_service import TeamService

logger = logging.getLogger("dgg_pm.services.auth")


class AuthService:
    """Evaluates role, team, and server permissions for task mutations and project operations."""

    def __init__(self, project_service: ProjectService, team_service: TeamService | None = None):
        self.project_service = project_service
        self.team_service = team_service

    @staticmethod
    def is_server_manager(user: discord.Member | discord.User) -> bool:
        """Checks if user has Discord administrator or manage_guild permissions."""
        perms = getattr(user, "guild_permissions", None)
        if perms is not None:
            admin = getattr(perms, "administrator", False)
            manage_guild = getattr(perms, "manage_guild", False)
            return bool(admin or manage_guild)
        return False

    async def is_project_lead(self, user: discord.Member | discord.User, project_id: UUID | None) -> bool:
        """Checks if the user is designated as the Project Lead or is a server manager."""
        if not project_id:
            return False
        if self.is_server_manager(user):
            return True
        project = await self.project_service.get_by_id(project_id)
        if not project or not project.lead_discord_id:
            return False
        user_id = getattr(user, "id", None)
        return bool(user_id and user_id == project.lead_discord_id)

    async def can_mutate_task(self, user: discord.Member | discord.User, task: Task) -> bool:
        """Determines if a user is authorized to edit, reassign, update status, archive, or add notes to a task.

        Authorized if:
        1. User is a Discord Server Manager (manage_guild / administrator).
        2. User is the task assignee.
        3. User is the task creator.
        4. User is the designated Project Lead for the task's project.
        5. User holds the project's mapped squad Discord Role.
        6. For legacy mapped teams: User holds a Discord Role mapped to any Team assigned to the project.
        """
        # 1. Server Manager bypass
        if self.is_server_manager(user):
            return True

        user_id = getattr(user, "id", None)

        # 2. Task Assignee
        if task.assignee_discord_id is not None and user_id == task.assignee_discord_id:
            return True

        # 3. Task Creator
        if user_id is not None and user_id == task.creator_discord_id:
            return True

        # 4. Project Lead / Contributor Role
        if task.project_id:
            project = await self.project_service.get_by_id(task.project_id)
            if project:
                if project.lead_discord_id and user_id == project.lead_discord_id:
                    return True
                if project.discord_role_id:
                    roles = getattr(user, "roles", [])
                    user_role_ids = {r.id for r in roles if hasattr(r, "id")}
                    if project.discord_role_id in user_role_ids:
                        return True

            # Legacy team fallback
            if self.team_service:
                teams = await self.project_service.list_teams_for_project(task.project_id)
                if teams:
                    roles = getattr(user, "roles", [])
                    if roles:
                        user_role_ids = {r.id for r in roles if hasattr(r, "id")}
                        if any(team.discord_role_id in user_role_ids for team in teams):
                            return True

        return False

    async def require_task_mutation(self, user: discord.Member | discord.User, task: Task) -> None:
        """Raises PermissionDeniedError if the user is not authorized to mutate the task."""
        if not await self.can_mutate_task(user, task):
            raise PermissionDeniedError(
                "You do not have permission to modify this task. "
                "You must be the assignee, creator, project lead, a squad member, or a server manager."
            )

    async def can_create_task_in_project(
        self,
        user: discord.Member | discord.User,
        project_id: UUID | None,
        guild_id: int | None = None,
    ) -> bool:
        """Determines if a user is authorized to create tasks in a project container or standalone.

        - Server Managers can create tasks in any project and standalone.
        - Standalone tasks (project_id=None): restricted to Server Managers and Team Leads.
        - Project Leads can create tasks in their projects.
        - If a project has a mapped squad Discord role: user must hold that role.
        - If a project has no role mapping and no mapped teams: open to all members.
        """
        # Server Manager bypass
        if self.is_server_manager(user):
            return True

        user_id = getattr(user, "id", None)

        if not project_id:
            # Standalone tasks are restricted to Server Managers (handled above) and Team Leads
            if self.team_service and user_id:
                guild = getattr(user, "guild", None)
                target_guild_id = (
                    guild.id if (guild and hasattr(guild, "id") and isinstance(guild.id, int)) else guild_id
                )
                if target_guild_id and isinstance(target_guild_id, int):
                    teams = await self.team_service.list_teams(target_guild_id)
                    for t in teams:
                        if await self.team_service.is_team_lead(t.id, user_id):
                            return True
            return False

        project = await self.project_service.get_by_id(project_id)
        if not project:
            return False

        if project.lead_discord_id and user_id == project.lead_discord_id:
            return True

        if project.discord_role_id:
            roles = getattr(user, "roles", [])
            user_role_ids = {r.id for r in roles if hasattr(r, "id")}
            return project.discord_role_id in user_role_ids

        # Legacy team fallback
        if self.team_service:
            teams = await self.project_service.list_teams_for_project(project_id)
            if teams:
                roles = getattr(user, "roles", [])
                if roles:
                    user_role_ids = {r.id for r in roles if hasattr(r, "id")}
                    return any(team.discord_role_id in user_role_ids for team in teams)

        # If project has no role and no legacy teams, open to all server members
        return True

    async def require_task_creation(
        self,
        user: discord.Member | discord.User,
        project_id: UUID | None,
        guild_id: int | None = None,
    ) -> None:
        """Raises PermissionDeniedError if the user cannot create tasks in the project."""
        if not await self.can_create_task_in_project(user, project_id, guild_id=guild_id):
            if not project_id:
                raise PermissionDeniedError(
                    "You do not have permission to create standalone tasks. "
                    "You must be a Team Lead or a server manager, or create the task inside an active project."
                )
            raise PermissionDeniedError(
                "You do not have permission to create tasks in this project. "
                "You must hold the project squad's Discord role, be the Project Lead, or be a server manager."
            )

    async def can_assign_task_to_user(
        self,
        guild: discord.Guild | None,
        target_user: discord.Member | discord.User | int | None,
        project_id: UUID | None,
    ) -> bool:
        """Determines if a target user is eligible to be assigned to a task.

        - If target_user is None (unassigning): always eligible (True).
        - If standalone task (project_id is None): any guild member is eligible.
        - If target_user is the Project Lead: always eligible.
        - If project has a mapped squad role: target user must hold that Discord role.
        - If project has assigned legacy teams: target user must hold at least one mapped team's role.
        - If project has no mapped role / teams: any guild member is eligible.
        """
        if target_user is None or not project_id:
            return True

        project = await self.project_service.get_by_id(project_id)
        if not project:
            return True

        user_id = target_user if isinstance(target_user, int) else getattr(target_user, "id", None)
        if project.lead_discord_id and user_id == project.lead_discord_id:
            return True

        member: Any = None
        if hasattr(target_user, "roles"):
            member = target_user
        elif guild and user_id and hasattr(guild, "get_member"):
            member = guild.get_member(user_id)

        if not member:
            return False

        roles = getattr(member, "roles", [])
        user_role_ids = {r.id for r in roles if hasattr(r, "id")}

        if project.discord_role_id:
            return project.discord_role_id in user_role_ids

        # Legacy team fallback
        if self.team_service:
            teams = await self.project_service.list_teams_for_project(project_id)
            if teams:
                return any(team.discord_role_id in user_role_ids for team in teams)

        return True

    async def require_task_assignee_eligibility(
        self,
        guild: discord.Guild | None,
        target_user: discord.Member | discord.User | int | None,
        project_id: UUID | None,
    ) -> None:
        """Raises PermissionDeniedError if the target user is not eligible for assignment."""
        if not await self.can_assign_task_to_user(guild, target_user, project_id):
            user_id = target_user.id if hasattr(target_user, "id") else target_user
            raise PermissionDeniedError(
                f"<@{user_id}> does not hold the squad Discord role for this project. "
                "Only members with the project's Discord role or the Project Lead can be assigned."
            )

    async def can_manage_team_leads(self, user: discord.Member | discord.User, team_id: UUID) -> bool:
        """Determines if a user can designate or remove team leads.

        Authorized if:
        1. User has Server Manager permissions (manage_guild / administrator).
        2. User is designated as a Team Lead in database AND currently holds the team's Discord role.
        """
        if self.is_server_manager(user):
            return True

        user_id = getattr(user, "id", None)
        if user_id is None or not isinstance(user_id, int):
            return False

        is_lead = await self.team_service.is_team_lead(team_id, user_id)
        if not is_lead:
            return False

        # Verify that the user still currently holds the team's Discord role
        if hasattr(user, "roles"):
            team = await self.team_service.get_by_id(team_id)
            if team:
                user_role_ids = {r.id for r in getattr(user, "roles", []) if hasattr(r, "id")}
                if team.discord_role_id not in user_role_ids:
                    return False

        return True

    async def require_team_lead_management(self, user: discord.Member | discord.User, team_id: UUID) -> None:
        """Raises PermissionDeniedError if the user cannot manage team leads."""
        if not await self.can_manage_team_leads(user, team_id):
            raise PermissionDeniedError(
                "You do not have permission to manage team leads for this team. "
                "You must be a Team Lead or a server manager."
            )

    async def can_manage_team_roster(self, user: discord.Member | discord.User, team_id: UUID) -> bool:
        return await self.can_manage_team_leads(user, team_id)

    async def require_team_roster_management(self, user: discord.Member | discord.User, team_id: UUID) -> None:
        await self.require_team_lead_management(user, team_id)
