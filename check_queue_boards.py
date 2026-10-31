import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs
from app.services.application_assistant.queue_preprocessor import get_preprocessor, get_stats

with session_scope() as db:
    jobs = list_autopilot_jobs(db)
    queued = [j for j in jobs if j.get('status') == 'QUEUED']
    
    # Check board distribution
    def get_board(url):
        u = (url or "").lower()
        if "greenhouse.io" in u or "greenhouse" in u:
            return "greenhouse"
        if "ashbyhq.com" in u or "ashby" in u:
            return "ashby"
        if "lever.co" in u or "lever" in u:
            return "lever"
        if "workday" in u or "myworkdayjobs" in u:
            return "workday"
        if "smartrecruiters" in u:
            return "smartrecruiters"
        if "workable" in u:
            return "workable"
        if "icims" in u:
            return "icims"
        if "taleo" in u:
            return "taleo"
        if "successfactors" in u or "sap" in u:
            return "successfactors"
        if "eightfold" in u:
            return "eightfold"
        if "breezy" in u:
            return "breezy"
        if "jobvite" in u:
            return "jobvite"
        if "recruitee" in u:
            return "recruitee"
        if "teamtailor" in u:
            return "teamtailor"
        return "other"
    
    from collections import Counter
    board_counts = Counter(get_board(j.get('applicationUrl')) for j in queued)
    print("QUEUED jobs by board:")
    for board, count in board_counts.most_common():
        print(f"  {board}: {count}")
    
    # Check match scores for greenhouse/ashby/lever jobs
    print("\nGreenhouse/Ashby/Lever jobs with match scores:")
    for j in queued:
        board = get_board(j.get('applicationUrl'))
        if board in ('greenhouse', 'ashby', 'lever'):
            print(f"  {j.get('company')} - {j.get('title')}: match={j.get('matchScore', 0)}%")

# Check queue preprocessor
print("\n=== QUEUE PREPROCESSOR ===")
preprocessor = get_preprocessor()
stats = get_stats()
print(f"Running: {preprocessor.is_running()}")
print(f"Stats: {stats}")