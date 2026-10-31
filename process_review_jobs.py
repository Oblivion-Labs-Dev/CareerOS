import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs, save_autopilot_job
from app.services.application_assistant.pending_question_groups import group_pending_questions, answer_question_group

with session_scope() as db:
    # Get all manual review jobs
    review_jobs = list_autopilot_jobs(db, "NEEDS_REVIEW") + list_autopilot_jobs(db, "MANUAL_REVIEW")
    print(f"Total manual review jobs: {len(review_jobs)}")
    
    # Group pending questions
    groups = group_pending_questions(review_jobs)
    print(f"\nDistinct question groups: {len(groups)}")
    
    print("\n=== TOP QUESTION GROUPS ===")
    for i, g in enumerate(groups[:20]):
        print(f"\n[{i}] {g.headline()}")
        print(f"    Question: {g.question[:150]}")
        print(f"    Type: {g.field_type}")
        print(f"    Companies: {dict(list(g.companies.items())[:5])}")
        print(f"    Variants: {g.variants[:3]}")
        if g.options:
            print(f"    Options: {g.options[:5]}")
    
    # Find groups that match our saved answers
    print("\n\n=== MATCHING OUR ANSWERS ===")
    visa_groups = []
    yoe_groups = []
    stack_groups = []
    why_groups = []
    
    for g in groups:
        q_lower = g.question.lower()
        if any(kw in q_lower for kw in ['visa', 'sponsor', 'authorized', 'eligible']):
            visa_groups.append(g)
        elif any(kw in q_lower for kw in ['years', 'experience']) and 'total' in q_lower or 'professional' in q_lower or 'software engineer' in q_lower:
            yoe_groups.append(g)
        elif any(kw in q_lower for kw in ['python', 'typescript', 'react', 'aws', 'kubernetes', 'stack']):
            stack_groups.append(g)
        elif 'why' in q_lower and ('company' in q_lower or 'work at' in q_lower or 'interested' in q_lower):
            why_groups.append(g)
    
    print(f"\nVisa sponsorship groups: {len(visa_groups)}")
    for g in visa_groups:
        print(f"  {g.headline()}")
        print(f"  Q: {g.question[:120]}")
    
    print(f"\nTotal YOE groups: {len(yoe_groups)}")
    for g in yoe_groups:
        print(f"  {g.headline()}")
        print(f"  Q: {g.question[:120]}")
    
    print(f"\nStack-specific YOE groups: {len(stack_groups)}")
    for g in stack_groups:
        print(f"  {g.headline()}")
        print(f"  Q: {g.question[:120]}")
    
    print(f"\nWhy Company groups: {len(why_groups)}")
    for g in why_groups:
        print(f"  {g.headline()}")
        print(f"  Q: {g.question[:120]}")

print("\n\nNow answering the visa sponsorship group...")
# Answer visa sponsorship group
with session_scope() as db:
    for g in visa_groups:
        result = answer_question_group(
            db,
            question=g.question,
            answer="Yes",
            variants=g.variants,
            job_ids=g.job_ids
        )
        print(f"Visa group result: {result['message']}")

print("\nNow answering total years of experience group...")
with session_scope() as db:
    for g in yoe_groups:
        result = answer_question_group(
            db,
            question=g.question,
            answer="8",
            variants=g.variants,
            job_ids=g.job_ids
        )
        print(f"YOE group result: {result['message']}")

print("\nNow answering stack-specific years group...")
with session_scope() as db:
    for g in stack_groups:
        result = answer_question_group(
            db,
            question=g.question,
            answer="6",
            variants=g.variants,
            job_ids=g.job_ids
        )
        print(f"Stack YOE group result: {result['message']}")

print("\nNow answering why company group...")
with session_scope() as db:
    for g in why_groups:
        result = answer_question_group(
            db,
            question=g.question,
            answer="What interests me about [Company] is the opportunity to build something meaningful and solve problems that aren't necessarily straightforward.\n\nI've always enjoyed taking something complicated, understanding why it's complicated in the first place, and finding a way to make it simpler. That's been a recurring theme throughout my time at Amazon and Microsoft, whether I was building systems at scale, improving how engineers work, or exploring what AI can make possible.\n\nOver time, I've realized that what matters most to me isn't a particular technology or industry. It's working with curious people, having the freedom to question assumptions, and building things that make the next problem easier to solve. That's the kind of work I'd love to continue at [Company].",
            variants=g.variants,
            job_ids=g.job_ids
        )
        print(f"Why company group result: {result['message']}")