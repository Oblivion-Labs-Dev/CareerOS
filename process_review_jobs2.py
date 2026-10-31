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
    print(f"Distinct question groups: {len(groups)}")
    
    # Find groups that match our saved answers
    visa_groups = []
    yoe_groups = []
    stack_groups = []
    why_groups = []
    
    for g in groups:
        q_lower = g.question.lower()
        if any(kw in q_lower for kw in ['visa', 'sponsor', 'authorized', 'eligible']):
            visa_groups.append(g)
        elif any(kw in q_lower for kw in ['years', 'experience']) and ('total' in q_lower or 'professional' in q_lower or 'software engineer' in q_lower or 'relevant' in q_lower):
            yoe_groups.append(g)
        elif any(kw in q_lower for kw in ['python', 'typescript', 'react', 'aws', 'kubernetes', 'stack']):
            stack_groups.append(g)
        elif 'why' in q_lower and ('company' in q_lower or 'work at' in q_lower or 'interested' in q_lower or 'excites' in q_lower):
            why_groups.append(g)
    
    print(f"Visa sponsorship groups: {len(visa_groups)}")
    print(f"Total YOE groups: {len(yoe_groups)}")
    print(f"Stack-specific YOE groups: {len(stack_groups)}")
    print(f"Why Company groups: {len(why_groups)}")
    
    # Write details to file
    with open('group_details.txt', 'w', encoding='utf-8') as f:
        f.write(f"Total manual review jobs: {len(review_jobs)}\n")
        f.write(f"Distinct question groups: {len(groups)}\n\n")
        
        f.write("=== VISA GROUPS ===\n")
        for g in visa_groups:
            f.write(f"\n  {g.headline()}\n")
            f.write(f"  Q: {g.question[:200]}\n")
            f.write(f"  Variants: {g.variants[:3]}\n")
            f.write(f"  Companies: {dict(list(g.companies.items())[:5])}\n")
        
        f.write("\n=== YOE GROUPS ===\n")
        for g in yoe_groups:
            f.write(f"\n  {g.headline()}\n")
            f.write(f"  Q: {g.question[:200]}\n")
            f.write(f"  Variants: {g.variants[:3]}\n")
        
        f.write("\n=== STACK YOE GROUPS ===\n")
        for g in stack_groups:
            f.write(f"\n  {g.headline()}\n")
            f.write(f"  Q: {g.question[:200]}\n")
        
        f.write("\n=== WHY COMPANY GROUPS ===\n")
        for g in why_groups:
            f.write(f"\n  {g.headline()}\n")
            f.write(f"  Q: {g.question[:200]}\n")

print("Details written to group_details.txt")

# Now answer the groups
print("\n\n=== ANSWERING GROUPS ===")

# Answer visa sponsorship groups
total_requeued = 0
with session_scope() as db:
    for g in visa_groups:
        result = answer_question_group(
            db,
            question=g.question,
            answer="Yes",
            variants=g.variants,
            job_ids=g.job_ids
        )
        print(f"Visa: requeued={result['requeuedCount']}, still_blocked={result['stillBlockedCount']}")
        total_requeued += result['requeuedCount']

# Answer total YOE groups
with session_scope() as db:
    for g in yoe_groups:
        result = answer_question_group(
            db,
            question=g.question,
            answer="8",
            variants=g.variants,
            job_ids=g.job_ids
        )
        print(f"YOE: requeued={result['requeuedCount']}, still_blocked={result['stillBlockedCount']}")
        total_requeued += result['requeuedCount']

# Answer stack-specific YOE groups
with session_scope() as db:
    for g in stack_groups:
        result = answer_question_group(
            db,
            question=g.question,
            answer="6",
            variants=g.variants,
            job_ids=g.job_ids
        )
        print(f"Stack YOE: requeued={result['requeuedCount']}, still_blocked={result['stillBlockedCount']}")
        total_requeued += result['requeuedCount']

# Answer why company groups - need to substitute company name
with session_scope() as db:
    for g in why_groups:
        # Determine company from the group's companies
        companies = list(g.companies.keys())
        if len(companies) == 1:
            company_name = companies[0]
            answer = g.question.replace('[Company]', company_name).replace('company', company_name)
            # Use the template with company substituted
            template = "What interests me about [Company] is the opportunity to build something meaningful and solve problems that aren't necessarily straightforward.\n\nI've always enjoyed taking something complicated, understanding why it's complicated in the first place, and finding a way to make it simpler. That's been a recurring theme throughout my time at Amazon and Microsoft, whether I was building systems at scale, improving how engineers work, or exploring what AI can make possible.\n\nOver time, I've realized that what matters most to me isn't a particular technology or industry. It's working with curious people, having the freedom to question assumptions, and building things that make the next problem easier to solve. That's the kind of work I'd love to continue at [Company]."
            answer = template.replace('[Company]', company_name)
        else:
            answer = "What interests me about [Company] is the opportunity to build something meaningful and solve problems that aren't necessarily straightforward.\n\nI've always enjoyed taking something complicated, understanding why it's complicated in the first place, and finding a way to make it simpler. That's been a recurring theme throughout my time at Amazon and Microsoft, whether I was building systems at scale, improving how engineers work, or exploring what AI can make possible.\n\nOver time, I've realized that what matters most to me isn't a particular technology or industry. It's working with curious people, having the freedom to question assumptions, and building things that make the next problem easier to solve. That's the kind of work I'd love to continue at [Company]."
        
        result = answer_question_group(
            db,
            question=g.question,
            answer=answer,
            variants=g.variants,
            job_ids=g.job_ids
        )
        print(f"Why {companies[:3] if len(companies)==1 else 'multi'}: requeued={result['requeuedCount']}, still_blocked={result['stillBlockedCount']}")
        total_requeued += result['requeuedCount']

print(f"\nTotal jobs requeued: {total_requeued}")