from __future__ import annotations

from uuid import UUID

from src.domain.enums import TeamRoleType
from src.domain.exceptions import TeamAlreadyExistsError
from src.domain.models import Team, TeamMember
from src.ports.repositories import ITeamRepo


class TeamService:
    def __init__(self, team_repo: ITeamRepo):
        self.team_repo = team_repo

    async def create_team(
        self,
        guild_id: int,
        name: str,
        discord_role_id: int,
    ) -> Team:
        existing = await self.team_repo.get_by_name(guild_id, name)
        if existing:
            raise TeamAlreadyExistsError(f"Team with name '{name}' already exists in this server.")

        team = Team(
            guild_id=guild_id,
            name=name.strip(),
            discord_role_id=discord_role_id,
        )
        return await self.team_repo.create(team)

    async def get_by_id(self, team_id: UUID) -> Team | None:
        return await self.team_repo.get_by_id(team_id)

    async def get_by_name(self, guild_id: int, name: str) -> Team | None:
        return await self.team_repo.get_by_name(guild_id, name)

    async def get_by_role_id(self, guild_id: int, role_id: int) -> Team | None:
        return await self.team_repo.get_by_role_id(guild_id, role_id)

    async def get_or_create_team_for_role(
        self,
        guild_id: int,
        role_id: int,
        role_name: str,
    ) -> Team:
        """Finds an existing team by role ID or name, or creates a new one."""
        team = await self.team_repo.get_by_role_id(guild_id, role_id)
        if team:
            return team

        team_by_name = await self.team_repo.get_by_name(guild_id, role_name.strip())
        if team_by_name:
            return team_by_name

        new_team = Team(
            guild_id=guild_id,
            name=role_name.strip(),
            discord_role_id=role_id,
        )
        return await self.team_repo.create(new_team)

    async def add_team_lead(self, team_id: UUID, user_discord_id: int) -> None:
        await self.team_repo.add_team_lead(team_id, user_discord_id)

    async def remove_team_lead(self, team_id: UUID, user_discord_id: int) -> None:
        await self.team_repo.remove_team_lead(team_id, user_discord_id)

    async def list_team_leads(self, team_id: UUID) -> list[int]:
        return await self.team_repo.list_team_leads(team_id)

    async def is_team_lead(self, team_id: UUID, user_discord_id: int) -> bool:
        return await self.team_repo.is_team_lead(team_id, user_discord_id)

    async def assign_member(
        self,
        team_id: UUID,
        user_discord_id: int,
        role_type: TeamRoleType = TeamRoleType.MEMBER,
    ) -> None:
        member = TeamMember(
            team_id=team_id,
            user_discord_id=user_discord_id,
            role_type=role_type,
        )
        await self.team_repo.assign_member(member)

    async def list_teams(self, guild_id: int) -> list[Team]:
        return await self.team_repo.list_teams(guild_id)

    async def list_members(self, team_id: UUID) -> list[TeamMember]:
        return await self.team_repo.list_members(team_id)
