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
    """Evaluates role, team, and server permissions for task mutations and team operations."""

    def __init__(self, project_service: ProjectService, team_service: TeamService):
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

    async def can_mutate_task(self, user: discord.Member | discord.User, task: Task) -> bool:
        """Determines if a user is authorized to edit, reassign, update status, archive, or add notes to a task.

        Authorized if:
        1. User is a Discord Server Manager (manage_guild / administrator).
        2. User is the task assignee.
        3. User is the task creator.
        4. For project-bound tasks: User holds a Discord Role mapped to any Team assigned to the project.
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

        # 4. Project Team Member
        if task.project_id:
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
                "You must be the assignee, creator, a member of the project team, or a server manager."
            )

    async def can_create_task_in_project(self, user: discord.Member | discord.User, project_id: UUID | None) -> bool:
        """Determines if a user is authorized to create tasks in a project container.

        - Standalone tasks (project_id=None) can be created by any guild member.
        - Project tasks require holding the mapped Team's Discord role or Server Manager permissions.
        - Projects without mapped teams require Server Manager permissions (strict default).
        """
        # Standalone task creation is open to all
        if not project_id:
            return True

        # Server Manager bypass
        if self.is_server_manager(user):
            return True

        # Check project team mapping
        teams = await self.project_service.list_teams_for_project(project_id)
        if teams:
            roles = getattr(user, "roles", [])
            if roles:
                user_role_ids = {r.id for r in roles if hasattr(r, "id")}
                if any(team.discord_role_id in user_role_ids for team in teams):
                    return True

        return False

    async def require_task_creation(self, user: discord.Member | discord.User, project_id: UUID | None) -> None:
        """Raises PermissionDeniedError if the user cannot create tasks in the project."""
        if not await self.can_create_task_in_project(user, project_id):
            raise PermissionDeniedError(
                "You do not have permission to create tasks in this project. "
                "You must hold the assigned team's Discord role or be a server manager."
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
        - If project has assigned teams: target user must hold at least one mapped team's Discord role.
        - If project has no mapped teams: any guild member is eligible.
        """
        if target_user is None or not project_id:
            return True

        teams = await self.project_service.list_teams_for_project(project_id)
        if not teams:
            return True

        member: Any = None
        if hasattr(target_user, "roles"):
            member = target_user
        elif guild and hasattr(target_user, "id"):
            member = guild.get_member(target_user.id)
        elif guild and isinstance(target_user, int):
            member = guild.get_member(target_user)

        if not member:
            return False

        roles = getattr(member, "roles", [])
        user_role_ids = {r.id for r in roles if hasattr(r, "id")}
        return any(team.discord_role_id in user_role_ids for team in teams)

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
                f"<@{user_id}> is not a member of any team assigned to this project. "
                "Only members with the project team's Discord role can be assigned."
            )

    async def can_manage_team_leads(self, user: discord.Member | discord.User, team_id: UUID) -> bool:
        """Determines if a user can designate or remove team leads.

        Authorized if:
        1. User has Server Manager permissions (manage_guild / administrator).
        2. User is designated as a Team Lead (TeamRoleType.LEAD) in database.
        """
        if self.is_server_manager(user):
            return True

        user_id = getattr(user, "id", None)
        if user_id is None or not isinstance(user_id, int):
            return False

        return await self.team_service.is_team_lead(team_id, user_id)

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
