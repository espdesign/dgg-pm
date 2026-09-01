"""Role and team-based authorization service for dgg-pm."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from src.domain.exceptions import PermissionDeniedError
from src.domain.models import Actor, Task

if TYPE_CHECKING:
    from src.services.project_service import ProjectService
    from src.services.team_service import TeamService

logger = logging.getLogger("dgg_pm.services.auth")


def _ensure_actor(actor: Actor | Any, guild: Any = None) -> Actor:
    """Ensures the input is a domain Actor struct, converting duck-typed callers if needed."""
    if isinstance(actor, Actor):
        return actor
    if actor is None:
        return Actor(user_id=0)

    user_id = getattr(actor, "id", 0) if not isinstance(actor, int) else actor
    perms = getattr(actor, "guild_permissions", None)
    is_admin = False
    if perms is not None:
        is_admin = bool(getattr(perms, "administrator", False) or getattr(perms, "manage_guild", False))

    role_ids: set[int] = set()
    roles = getattr(actor, "roles", None)
    if roles:
        role_ids = {r.id for r in roles if hasattr(r, "id")}
    elif guild and hasattr(guild, "get_member") and user_id:
        member = guild.get_member(user_id)
        if member:
            member_perms = getattr(member, "guild_permissions", None)
            if member_perms:
                is_admin = bool(
                    getattr(member_perms, "administrator", False) or getattr(member_perms, "manage_guild", False)
                )
            member_roles = getattr(member, "roles", None)
            if member_roles:
                role_ids = {r.id for r in member_roles if hasattr(r, "id")}

    return Actor(user_id=user_id, role_ids=frozenset(role_ids), is_admin=is_admin)


class AuthService:
    """Evaluates role, team, and server permissions for task mutations and project operations."""

    def __init__(self, project_service: ProjectService, team_service: TeamService | None = None):
        self.project_service = project_service
        self.team_service = team_service

    @staticmethod
    def is_server_manager(actor: Actor | Any) -> bool:
        """Checks if the actor has server manager (administrator or manage_guild) permissions."""
        act = _ensure_actor(actor)
        return act.is_admin

    async def is_project_lead(self, actor: Actor | Any, project_id: UUID | None) -> bool:
        """Checks if the actor is designated as the Project Lead or is a server manager."""
        if not project_id:
            return False
        act = _ensure_actor(actor)
        if self.is_server_manager(act):
            return True
        project = await self.project_service.get_by_id(project_id)
        if not project or not project.lead_discord_id:
            return False
        return bool(act.user_id and act.user_id == project.lead_discord_id)

    async def can_mutate_task(self, actor: Actor | Any, task: Task) -> bool:
        """Determines if an actor is authorized to edit, reassign, update status, archive, or add notes to a task.

        Authorized if:
        1. Actor is a Server Manager (administrator / manage_guild).
        2. Actor is the task assignee.
        3. Actor is the task creator.
        4. Actor is the designated Project Lead for the task's project.
        5. Actor holds the project's mapped squad Discord Role.
        6. For legacy mapped teams: Actor holds a role mapped to any Team assigned to the project.
        """
        act = _ensure_actor(actor)

        # 1. Server Manager bypass
        if self.is_server_manager(act):
            return True

        # 2. Task Assignee
        if task.assignee_discord_id is not None and act.user_id == task.assignee_discord_id:
            return True

        # 3. Task Creator
        if act.user_id is not None and act.user_id == task.creator_discord_id:
            return True

        # 4. Project Lead / Contributor Role
        if task.project_id:
            project = await self.project_service.get_by_id(task.project_id)
            if project:
                if project.lead_discord_id and act.user_id == project.lead_discord_id:
                    return True
                if project.discord_role_id and project.discord_role_id in act.role_ids:
                    return True

            # Legacy team fallback
            if self.team_service:
                teams = await self.project_service.list_teams_for_project(task.project_id)
                if teams:
                    if any(team.discord_role_id in act.role_ids for team in teams):
                        return True

        return False

    async def require_task_mutation(self, actor: Actor | Any, task: Task) -> None:
        """Raises PermissionDeniedError if the actor is not authorized to mutate the task."""
        if not await self.can_mutate_task(actor, task):
            raise PermissionDeniedError(
                "You do not have permission to modify this task. "
                "You must be the assignee, creator, project lead, a squad member, or a server manager."
            )

    async def can_create_task_in_project(
        self,
        actor: Actor | Any,
        project_id: UUID | None,
        guild_id: int | None = None,
    ) -> bool:
        """Determines if an actor is authorized to create tasks in a project container or standalone.

        - Server Managers can create tasks in any project and standalone.
        - Standalone tasks (project_id=None): restricted to Server Managers and Team Leads.
        - Project Leads can create tasks in their projects.
        - If a project has a mapped squad Discord role: actor must hold that role.
        - If a project has no role mapping and no mapped teams: open to all members.
        """
        act = _ensure_actor(actor)

        # Server Manager bypass
        if self.is_server_manager(act):
            return True

        if not project_id:
            # Standalone tasks are restricted to Server Managers and Team Leads
            if self.team_service and act.user_id:
                target_guild_id = getattr(getattr(actor, "guild", None), "id", guild_id)
                if target_guild_id and isinstance(target_guild_id, int):
                    teams = await self.team_service.list_teams(target_guild_id)
                    for t in teams:
                        if await self.team_service.is_team_lead(t.id, act.user_id):
                            return True
            return False

        project = await self.project_service.get_by_id(project_id)
        if not project:
            return False

        if project.lead_discord_id and act.user_id == project.lead_discord_id:
            return True

        if project.discord_role_id:
            return project.discord_role_id in act.role_ids

        # Legacy team fallback
        if self.team_service:
            teams = await self.project_service.list_teams_for_project(project_id)
            if teams:
                return any(team.discord_role_id in act.role_ids for team in teams)

        # If project has no role and no legacy teams, open to all server members
        return True

    async def require_task_creation(
        self,
        actor: Actor | Any,
        project_id: UUID | None,
        guild_id: int | None = None,
    ) -> None:
        """Raises PermissionDeniedError if the actor cannot create tasks in the project."""
        if not await self.can_create_task_in_project(actor, project_id, guild_id=guild_id):
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
        guild_or_target: Any,
        target_user: Any = None,
        project_id: UUID | None = None,
    ) -> bool:
        """Determines if a target user/actor is eligible to be assigned to a task.

        Supports both:
        - can_assign_task_to_user(target_actor, project_id)
        - can_assign_task_to_user(guild, target_user, project_id) (legacy signature)
        """
        guild = None
        target = guild_or_target
        pid = project_id

        if project_id is None and isinstance(target_user, (UUID, type(None))):
            # Signature: (target_actor, project_id)
            target = guild_or_target
            pid = target_user
            guild = None
        else:
            # Signature: (guild, target_user, project_id)
            guild = guild_or_target
            target = target_user
            pid = project_id

        if target is None or not pid:
            return True

        project = await self.project_service.get_by_id(pid)
        if not project:
            return True

        act = _ensure_actor(target, guild=guild)

        if project.lead_discord_id and act.user_id == project.lead_discord_id:
            return True

        if project.discord_role_id:
            return project.discord_role_id in act.role_ids

        # Legacy team fallback
        if self.team_service:
            teams = await self.project_service.list_teams_for_project(pid)
            if teams:
                return any(team.discord_role_id in act.role_ids for team in teams)

        return True

    async def require_task_assignee_eligibility(
        self,
        guild_or_target: Any,
        target_user: Any = None,
        project_id: UUID | None = None,
    ) -> None:
        """Raises PermissionDeniedError if the target user is not eligible for assignment."""
        if not await self.can_assign_task_to_user(guild_or_target, target_user, project_id):
            target = target_user if target_user is not None else guild_or_target
            user_id = getattr(target, "user_id", getattr(target, "id", target))
            raise PermissionDeniedError(
                f"<@{user_id}> does not hold the squad Discord role for this project. "
                "Only members with the project's Discord role or the Project Lead can be assigned."
            )

    async def can_manage_team_leads(self, actor: Actor | Any, team_id: UUID) -> bool:
        """Determines if an actor can designate or remove team leads.

        Authorized if:
        1. Actor has Server Manager permissions (is_admin).
        2. Actor is designated as a Team Lead in database AND currently holds the team's role.
        """
        act = _ensure_actor(actor)

        if self.is_server_manager(act):
            return True

        if not act.user_id:
            return False

        if not self.team_service:
            return False

        is_lead = await self.team_service.is_team_lead(team_id, act.user_id)
        if not is_lead:
            return False

        # Verify that the actor still currently holds the team's role
        team = await self.team_service.get_by_id(team_id)
        if team and team.discord_role_id not in act.role_ids:
            return False

        return True

    async def require_team_lead_management(self, actor: Actor | Any, team_id: UUID) -> None:
        """Raises PermissionDeniedError if the actor cannot manage team leads."""
        if not await self.can_manage_team_leads(actor, team_id):
            raise PermissionDeniedError(
                "You do not have permission to manage team leads for this team. "
                "You must be a Team Lead or a server manager."
            )

    async def can_manage_team_roster(self, actor: Actor | Any, team_id: UUID) -> bool:
        return await self.can_manage_team_leads(actor, team_id)

    async def require_team_roster_management(self, actor: Actor | Any, team_id: UUID) -> None:
        await self.require_team_lead_management(actor, team_id)
