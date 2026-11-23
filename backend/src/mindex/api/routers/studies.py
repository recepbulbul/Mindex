"""`/studies` (#54): the C0-C3 x seed groups of experiments and their condition comparison.

Reads need a session; creating needs the researcher role and starting the study's owner.
The rules live in `mindex.services.study`, which the CLI (`mindex study ...`) shares.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from mindex.api.deps import CurrentUser, JobQueueDep, Researcher, SessionDep, SettingsDep
from mindex.api.schemas import StudyComparisonOut, StudyCreate, StudyOut
from mindex.db.models import Study
from mindex.services.study import compare, create_study, get_study, queue_study, study_out

router = APIRouter(prefix="/studies", tags=["studies"])

NOT_FOUND = "Çalışma bulunamadı."
NOT_OWNER = "Bu çalışma başka bir araştırmacıya ait; yalnızca sahibi başlatabilir."
NO_RESULTS = "Çalışmanın henüz tamamlanan koşusu yok."


def _study(session: SessionDep, study_id: str) -> Study:
    study = get_study(session, study_id)
    if study is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return study


@router.get("")
def list_studies(session: SessionDep, _: CurrentUser) -> list[StudyOut]:
    rows = session.scalars(select(Study).order_by(Study.created_at.desc()))
    return [study_out(session, s) for s in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create(
    body: StudyCreate, session: SessionDep, settings: SettingsDep, user: Researcher
) -> StudyOut:
    """Every condition x every seed as draft experiments (`smoke`: short period, one seed)."""
    return study_out(session, create_study(session, settings, user.id, body))


@router.get("/{study_id}")
def get(study_id: str, session: SessionDep, _: CurrentUser) -> StudyOut:
    return study_out(session, _study(session, study_id))


@router.post(
    "/{study_id}/start",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Koşucu çalıştıramaz"}},
)
def start(
    study_id: str,
    session: SessionDep,
    settings: SettingsDep,
    user: Researcher,
    jobs: JobQueueDep,
) -> StudyOut:
    """Queue every draft or failed run, seed by seed (all conditions of a seed first)."""
    study = _study(session, study_id)
    if study.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_OWNER)
    for experiment_id in queue_study(session, settings, study):
        jobs.submit(experiment_id)
    return study_out(session, study)


@router.get(
    "/{study_id}/comparison",
    responses={status.HTTP_409_CONFLICT: {"description": NO_RESULTS}},
)
def comparison(study_id: str, session: SessionDep, _: CurrentUser) -> StudyComparisonOut:
    """Per condition over its completed runs, with block-bootstrap CIs (see `bootstrap`)."""
    result = compare(session, _study(session, study_id))
    if result is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_RESULTS)
    return result
