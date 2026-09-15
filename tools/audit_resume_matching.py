"""Read-only comparison of saved JDs. No queue writes or generation API calls."""
import sys, os, json, sqlite3, time, re, statistics, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api'))
os.environ['HF_HUB_OFFLINE'] = '1'
from app.services.resume_intelligence.baseline_document import load_baseline, render_baseline
from app.services.resume_intelligence.minimal_tailoring import tailor, TailoringConfig
from app.services.resume_intelligence.match_engine import match_corpus_to_job
from app.services.application_assistant.job_matching import match_job, _parse_qualifications
from app.services.application_assistant.mistral_resume_match import _is_evidenced, score_job_against_resume
from app.services.application_assistant import candidate_match_context as context
from app.services.application_assistant.tailored_match import build_submitted_resume_text
from app.services.resume_intelligence import semantic
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
IDS=['aa_job_708e8ad026606592','aa_job_fba07128528d5d33','aa_job_a606c0683dfa9df9','aa_job_2e04dbaa540c2c7f','aa_job_a6ece0cf0fc31e17','aa_job_9b50e2e9dd066ddc','aa_job_495d1c255ba26e39','aa_job_9d3c4f4675c4efaf','aa_job_ad1fee05332fa43e','aa_robinhood_7263592','aa_job_1c42ec1168c9f592','aa_airbnb_7453202']
# A small benchmark diagnostic, deliberately not a calibrated hiring/ATS score.
TERMS=['Python','Java','JavaScript','TypeScript','C#','C++','Go','Rust','Kotlin','Swift','React','Angular','SQL','PostgreSQL','MySQL','Redis','Kafka','Kubernetes','Docker','AWS','Azure','GCP','Terraform','Linux','GraphQL','REST','gRPC','Spark','PyTorch','TensorFlow','SageMaker','distributed systems','machine learning','observability','CI/CD','microservices','Android','iOS']
def has(text,term):
 return bool(re.search(r'(?<![\w+#])'+re.escape(term)+r'(?![\w+#])',text,re.I))
def technical(text,jd):
 required,preferred=_parse_qualifications(jd)
 scope='\n'.join(required+preferred) or jd
 requested=[t for t in TERMS if has(scope,t)]
 matched=[t for t in requested if has(text,t)]
 return {'score':round(100*len(matched)/len(requested),1) if requested else None,'matched':matched,'missing':[t for t in requested if t not in matched],'terms':len(requested)}
def measured(fn):
 a=time.perf_counter();result=fn();return result,round((time.perf_counter()-a)*1000,2)

def main():
 connection=sqlite3.connect('file:'+str(ROOT/'apps/api/data/career_os.db').replace('\\','/')+'?mode=ro',uri=True)
 def kv(k):
  row=connection.execute('select value from kv_store where key=?',(k,)).fetchone();return json.loads(row[0]) if row else {}
 profile=kv('profile');records=[json.loads(p) for(p,) in connection.execute("select payload from entities where entity_type='accomplishment'")]
 jobs={j['id']:j for(p,) in connection.execute("select payload from entities where entity_type='aa_discovered_job'") if (j:=json.loads(p)).get('id') in IDS}
 connection.close();base=load_baseline();before=base['text'];rows=[]
 for ident in IDS:
  j=jobs[ident];jd=j['description'];title=j['title']
  result,tailor_ms=measured(lambda:tailor(records,jd,title,config=TailoringConfig(**(profile.get('resumeTailoringConfig') or {}))))
  data=render_baseline(result)
  with pymupdf.open(stream=data,filetype='pdf') as doc:after=doc[0].get_text(sort=True);pages=len(doc)
  match_before,bms=measured(lambda:match_job(j,profile,documents={'defaultResume':{'parsedText':before}},accomplishments=records))
  match_after,ams=measured(lambda:match_job(j,profile,documents={'defaultResume':{'parsedText':after}},accomplishments=records))
  corpus_before,cms=measured(lambda:match_corpus_to_job(records,jd,job_title=title,profile=profile,resume_text=before))
  corpus_after,_=measured(lambda:match_corpus_to_job(records,jd,job_title=title,profile=profile,resume_text=after))
  prototype,pms=measured(lambda:technical(after,jd))
  rows.append({'id':ident,'company':j.get('company'),'title':title,'jdChars':len(jd),'candidateBefore':match_before['overallScore'],'candidateAfter':match_after['overallScore'],'corpusBefore':corpus_before['overallScore'],'corpusAfter':corpus_after['overallScore'],'technicalDiagnostic':prototype,'coverageDiagnostic':result['requirementCoverage'],'decisions':{d:sum(b['decision']==d for b in result['resumeBullets']) for d in ('KEEP','REORDER','REPLACE')},'identicalPdf':data==(ROOT/'apps/api/data/approved-resume.pdf').read_bytes(),'pages':pages,'semantic':result['rankingDebug']['semanticAvailable'],'ms':{'tailor':tailor_ms,'candidate':ams,'corpus':cms,'prototype':pms}})
  print(json.dumps(rows[-1]),flush=True)
 # Controlled probes with known answers: separate algorithm flaws from JD ambiguity.
 probes={}
 probes['substringGoInDjango']=_is_evidenced('Go','built django services',set())
 probes['shortSkillsTokenized']=sorted(context.extract_keywords('Go C# C++ Rust Python'))
 probes['directResumeProof']=match_corpus_to_job([], 'Required: Kubernetes Python.',resume_text='Built Kubernetes Python services.')['overallScore']
 probes['compoundQualification']=match_job({'title':'Engineer','description':'Requirements\nExperience developing Rust kernels for embedded avionics safety certification.'},{'skills':['experience']})['requiredCoverage']
 probes['omittedRequirements']=match_job({'title':'Engineer','description':'Build Kubernetes infrastructure.'},{'skills':['Kubernetes']})['requiredCoverage']
 probes['goBoundaryPrototype']=has('built django services','Go')
 probes['shortSkillsPrototype']=[t for t in ('Go','C#','C++') if has('Go C# C++',t)]
 probes['negatedSkillPrototype']=technical('I have no Kubernetes experience.','Required: Kubernetes.')['score']
 probes['legacySubmittedTextDuplicates']=build_submitted_resume_text('Original resume without legacy employer headings',['New evidence.']).startswith('Original resume')
 # Isolate the PDF text cache key: two equally-sized different attachments.
 parser=context.extract_text_from_attachment
 context._resume_text_cache.clear()
 context.extract_text_from_attachment=lambda attachment:attachment['base64']
 a=context._cached_resume_text({'id':'same','base64':'AAAA'});b=context._cached_resume_text({'id':'same','base64':'BBBB'})
 context.extract_text_from_attachment=parser;context._resume_text_cache.clear()
 probes['equalLengthCacheStale']=a==b
 class CapturingClient:
  enabled=True
  async def complete(self,prompt,**kwargs):
   probes['tailRequirementSurvivesPrompt']='CRITICAL_FINAL_REQUIREMENT' in prompt
   return {'success':False}
 asyncio.run(score_job_against_resume(CapturingClient(),{'description':'Company introduction. '*240+'Requirements\nCRITICAL_FINAL_REQUIREMENT','title':'Engineer'},candidate_summary=before,evidence_text=before.lower(),evidence_terms=set()))
 report={'rows':rows,'probes':probes,'timingsMedianMs':{key:statistics.median(r['ms'][key] for r in rows[1:]) for key in ('tailor','candidate','corpus','prototype')}}
 out=ROOT/'tmp/resume-match-audit';out.mkdir(exist_ok=True,parents=True);(out/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k!='rows'}),flush=True)
if __name__=='__main__':main()

