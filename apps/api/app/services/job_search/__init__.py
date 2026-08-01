"""Job search services (ai-job-search patterns ported to CareerOS)."""

from app.services.job_search.cover_letter_pipeline import generate_cover_letter_with_review
from app.services.job_search.html_report import build_analytics_summary, render_html_report
from app.services.job_search.job_evaluation import evaluate_job_fit, rank_jobs
from app.services.job_search.outcome_archive import list_outcome_archives, write_outcome_archive

__all__ = [
    "build_analytics_summary",
    "evaluate_job_fit",
    "generate_cover_letter_with_review",
    "list_outcome_archives",
    "rank_jobs",
    "render_html_report",
    "write_outcome_archive",
]
