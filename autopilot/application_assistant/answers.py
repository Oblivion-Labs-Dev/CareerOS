"""Application Assistant API routes — answers domain."""

from ._common import *  # noqa: F401,F403

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])


# ── Answer Library ────────────────────────────────────────────────────────────

@router.get("/answers")
def list_answers(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "answers": list_answer_library(db)}


@router.post("/answers")
def create_answer(payload: AnswerPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    answer = upsert_answer(db, payload.model_dump())
    return {"success": True, "answer": answer}


@router.delete("/answers/{answer_id}")
def remove_answer(answer_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    deleted = delete_answer(db, answer_id)
    return {"success": deleted}


