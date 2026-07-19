from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.store import (
    Base,
    EntityStore,
    RESUME_CORPUS_SEED_PATH,
    get_entity,
    seed_resume_corpus_if_needed,
)
from app.db.resume_corpus_seed import load_resume_corpus_seed


def test_shared_resume_corpus_seed_has_26_unique_accomplishments() -> None:
    records = load_resume_corpus_seed(RESUME_CORPUS_SEED_PATH)

    assert len(records) == 26
    assert len({record["id"] for record in records}) == 26


def test_seed_imports_only_missing_ids_and_preserves_existing_records() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    seeds = [
        {
            "id": "existing-accomplishment",
            "company": "Seed company",
            "title": "Seed title",
            "currentBullet": "Seed bullet",
            "missing": ["Architecture"],
        },
        {
            "id": "new-accomplishment",
            "company": "Microsoft",
            "title": "Adaptive Protection",
            "currentBullet": "Built Adaptive Protection.",
            "metrics": [
                {
                    "name": "AI agents",
                    "value": "237K",
                    "source": "Current resume",
                    "verification": "needs-evidence",
                }
            ],
            "missing": ["Architecture"],
        },
    ]

    with Session(engine) as db:
        original = {
            "id": "existing-accomplishment",
            "company": "User-edited company",
            "project": "User-edited title",
            "customField": "must survive",
        }
        db.add(
            EntityStore(
                id="existing-accomplishment",
                entity_type="accomplishment",
                payload=original,
            )
        )
        db.commit()

        assert seed_resume_corpus_if_needed(db, seeds) == 1
        db.flush()

        assert get_entity(db, "accomplishment", "existing-accomplishment") == original
        imported = get_entity(db, "accomplishment", "new-accomplishment")
        assert imported is not None
        assert imported["project"] == "Adaptive Protection"
        assert imported["resumeEvolution"]["current"] == "Built Adaptive Protection."
        assert imported["metricMetadata"]["new-accomplishment-metric-0"]["verification"] == "needs-evidence"

        assert seed_resume_corpus_if_needed(db, seeds) == 0
