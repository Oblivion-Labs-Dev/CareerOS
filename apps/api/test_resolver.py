import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'd:/1 - Projects/Projects/CareerOS/CareerOS/apps/api')
import asyncio
from app.db.store import session_scope, get_kv
from app.services.application_assistant.persistence import list_answer_library
from app.services.application_assistant.structured_answer_engine import resolve_application_question

async def main():
    with session_scope() as db:
        profile = get_kv(db, "profile") or {}
        answer_lib = list_answer_library(db)
        print("PROFILE:", profile)
        print("ANSWER LIB COUNT:", len(answer_lib))
        
        for q in ["First Name", "Last Name", "Email", "Phone", "Resume/CV", "LinkedIn Profile"]:
            res = await resolve_application_question(
                db=answer_lib,
                question_text=q,
                canonical_key=q.lower().replace(" ", "").replace("/", ""),
                options=None,
                profile=profile
            )
            print(f"Question: '{q}' -> res: {res}")

asyncio.run(main())
