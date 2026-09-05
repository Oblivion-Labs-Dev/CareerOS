import sys
from pathlib import Path

# Add apps/api to path
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / "apps" / "api"))

from app.db.store import session_scope, get_kv, set_kv, new_id, now_iso
from app.services.application_assistant.persistence import upsert_answer

def main():
    with session_scope() as db:
        prof = get_kv(db, 'profile') or {}
        prof['school'] = 'Santa Clara University'
        prof['degree'] = "Master's Degree"
        prof['discipline'] = 'Computer Science'
        prof['major'] = 'Computer Science'
        prof['education'] = [
            {'school': 'Santa Clara University', 'degree': "Master's Degree", 'discipline': 'Computer Science'},
            {'school': 'Pune University', 'degree': "Bachelor's Degree", 'discipline': 'Computer Engineering'}
        ]
        prof['testScores'] = {'sat': 'N/A', 'act': 'N/A', 'gre': 'N/A', 'gmat': 'N/A'}
        prof['actScore'] = 'N/A'
        prof['satScore'] = 'N/A'
        prof['greScore'] = 'N/A'
        prof['securityClearance'] = 'None'
        prof['previousEmployment'] = 'No'
        prof['employmentAgreements'] = 'No'
        prof['essentialFunctions'] = 'Yes'
        set_kv(db, 'profile', prof)
        print('Successfully updated profile in CareerOS KV store.')

        answers = [
            ('School', 'Santa Clara University'),
            ('University', 'Santa Clara University'),
            ('Degree', "Master's Degree"),
            ('Discipline', 'Computer Science'),
            ('Major', 'Computer Science'),
            ('SAT Score', 'N/A'),
            ('ACT Score', 'N/A'),
            ('GRE Score', 'N/A'),
            ('Active Security Clearance', 'None'),
            ('Active Security Clearance(s)', 'None'),
            ('Security Clearance', 'None'),
            ('Are you subject to any employment agreements and/or post-employment restrictions', 'No'),
            ('Have you previously worked at or consulted for', 'No'),
            ('Have you previously been employed at', 'No'),
            ('Have you interviewed with', 'No'),
            ('How did you first learn about', 'LinkedIn'),
            ('How did you hear about this job', 'LinkedIn'),
            ('Is your current location Bangalore', 'No'),
            ('Can you perform all of the essential functions of this role with or without reasonable accommodations', 'Yes'),
            ('What is the source of your right to work', 'Visa / Work Permit (H-1B)'),
        ]
        for q, a in answers:
            upsert_answer(db, {
                'question': q,
                'questionPattern': q.lower(),
                'fieldKey': q.lower().replace(' ', '_'),
                'canonicalAnswer': a,
                'source': 'USER_ANSWER_BANK',
                'verified': True,
            })
        print(f'Successfully persisted {len(answers)} verified answers to CareerOS Answer Bank.')

if __name__ == '__main__':
    main()
