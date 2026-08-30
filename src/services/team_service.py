from uuid import UUID

from src.domain.enums import TeamRoleType
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
            raise ValueError(f"Team with name '{name}' already exists in this server.")

        team = Team(
            guild_id=guild_id,
            name=name.strip(),
            discord_role_id=discord_role_id,
        )
        return await self.team_repo.create(team)

    async def get_by_name(self, guild_id: int, name: str) -> Team | None:
        return await self.team_repo.get_by_name(guild_id, name)

    async def get_by_role_id(self, guild_id: int, role_id: int) -> Team | None:
        return await self.team_repo.get_by_role_id(guild_id, role_id)

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
