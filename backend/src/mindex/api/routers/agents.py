"""`/agents`: the agent catalogue experiments choose from (seeded by migration 0002)."""

from fastapi import APIRouter
from sqlalchemy import select

from mindex.api.deps import CurrentUser, SessionDep
from mindex.api.schemas import AgentOut
from mindex.db.models import AgentRow

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
def list_agents(session: SessionDep, _: CurrentUser) -> list[AgentOut]:
    rows = session.scalars(select(AgentRow).order_by(AgentRow.kind, AgentRow.slug))
    return [AgentOut(id=a.slug, name=a.name, kind=a.kind, persona=a.persona) for a in rows]
