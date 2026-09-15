"""Continuous background preparation of the persistent Autopilot queue.

The Autopilot applies to one job at a time. That leaves the machine idle for
everything *except* the browser session, so this service keeps the pipeline

    Job Scraper -> dedupe -> eligibility filters -> Mistral resume/JD match
    -> match score -> queue

running the whole time an application is in flight, and re-orders the pending
queue whenever a newly discovered posting outranks what is already waiting.

Design notes
------------
* The queue is deliberately **unbounded**. Nothing here caps how many postings
  may sit in ``QUEUED``; the only capped number in this system is the E2E test's
  submission count, which lives in the test, not in the queue.
* Applications stay strictly sequential — this service never submits anything.
  It only reads discovered postings, scores them, and writes ``QUEUED`` rows.
* Match scoring is Mistral running under Ollama (see ``mistral_resume_match``).
  A posting the model could not score is left unscored and retried on a later
  cycle rather than being persisted with a fake zero.
* Every LLM call happens *outside* an open SQLAlchemy session. A scoring pass
  takes tens of seconds on this hardware, and holding a SQLite session open
  across it is what previously produced "database is locked" during a live run.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from app.db.store import get_kv, new_id, now_iso, session_scope, set_kv
from app.services.application_assistant.candidate_match_context import load_match_context
from app.services.application_assistant.domain import AutopilotJobStatus
from app.services.application_assistant.job_filter_ranker import (
    evaluate_hard_filters,
    filter_and_rank_jobs,
    queue_priority_score,
)
from app.services.application_assistant.mistral_resume_match import (
    build_mistral_match_client,
    score_jobs_against_resume,
)
from app.services.application_assistant.persistence import (
    _canonical_url_key,
    _composite_job_key,
    list_autopilot_jobs,
    list_discovered_jobs,
    save_autopilot_job,
    upsert_discovered_job,
)
from app.services.intelligence.night_batch_config import (
    HIGH_QUEUE_WATERMARK,
    LOW_QUEUE_WATERMARK,
)

logger = logging.getLogger(__name__)

STATS_KV_KEY = "autopilot_queue_preprocessor"

# How long to wait between preparation cycles when there is nothing new to do.
IDLE_CYCLE_SECONDS = 30.0
# How many postings to hand Mistral per cycle. Kept small so the queue keeps
# growing steadily while leaving the local GPU available to the resume
# tailoring of the application that is actively running.
SCORE_BATCH_SIZE = 6
SCORE_CONCURRENCY = 2
# Re-run the scraper at most this often; the job boards do not change faster.
SCRAPE_INTERVAL_SECONDS = 45 * 60
# How recently an APPLYING row must have been written to still count as a
# live submission rather than an orphan left behind by a killed run.
APPLYING_FRESHNESS_SECONDS = 600

# How often to check the inbox for confirmations of manually-finished
# applications. Every cycle would mean an IMAP round-trip every few seconds
# for a mailbox that changes at human speed.
RECONCILE_EVERY_N_CYCLES = 10
# Queue depth is governed by high/low watermarks (app.services.intelligence.
# night_batch_config) instead of a single fixed cap: intake pauses once QUEUED
# reaches HIGH_QUEUE_WATERMARK, and resumes once it drops back to or below
# LOW_QUEUE_WATERMARK, so Night Batch always has jobs prepared ahead of time
# without piling up unbounded, uncontrolled work. Rows already queued are
# never removed to get under the ceiling.
# Match scoring is the only stage that loads the local Ollama model, and it
# holds several GB of RAM resident for as long as the preprocessor keeps
# cycling — on this 8GB-GPU laptop that is what makes the machine crawl during
# an Autopilot run. Set CAREEROS_LOCAL_LLM=off to keep the model unloaded: the
# pipeline still scrapes, dedupes, filters, enqueues and re-ranks, it just
# stops scoring *new* postings, so already-scored jobs remain fully usable.
LOCAL_LLM_ENABLED = os.environ.get("CAREEROS_LOCAL_LLM", "on").strip().lower() not in ("off", "0", "false")


def _empty_stats() -> dict[str, Any]:
    return {
        "running": False,
        "cycles": 0,
        "jobsDiscovered": 0,
        "jobsPreprocessed": 0,
        "jobsEnqueued": 0,
        "jobsRejectedByFilters": 0,
        "jobsDeduped": 0,
        "scraperAdditions": 0,
        "scraperSnapshotSize": 0,
        "queueSize": 0,
        "lastScrapeStartedAt": None,
        "lastCycleAt": None,
        "lastError": "",
        "matchModel": "",
        "yieldingToApplication": False,
        "queueAtCapacity": False,
        "queueReplenishing": True,
        "queueBelowLowWatermark": True,
        "lowQueueWatermark": LOW_QUEUE_WATERMARK,
        "highQueueWatermark": HIGH_QUEUE_WATERMARK,
    }


def get_stats() -> dict[str, Any]:
    with session_scope() as db:
        return {**_empty_stats(), **(get_kv(db, STATS_KV_KEY) or {})}


class QueuePreprocessor:
    """Singleton background worker preparing future Autopilot jobs."""

    _instance: QueuePreprocessor | None = None

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = False
        self._last_scrape_at: float = 0.0
        self.stats: dict[str, Any] = _empty_stats()

    @classmethod
    def get_instance(cls) -> QueuePreprocessor:
        if cls._instance is None:
            cls._instance = QueuePreprocessor()
        return cls._instance

    # ── lifecycle ────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, *, scrape: bool = True) -> dict[str, Any]:
        if self.is_running():
            return {"success": True, "status": "already_running", "stats": self.stats}
        self._stop = False
        if not scrape:
            # Skip the first scrape by pretending one just happened.
            self._last_scrape_at = time.monotonic()
        self.stats = {**_empty_stats(), "running": True}
        self._persist_stats()
        self._task = asyncio.create_task(self._loop())

        def _done(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception():
                logger.error("Queue preprocessor crashed: %s", task.exception(), exc_info=task.exception())

        self._task.add_done_callback(_done)
        return {"success": True, "status": "started"}

    async def stop(self) -> dict[str, Any]:
        self._stop = True
        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
        self._task = None
        self.stats["running"] = False
        self._persist_stats()
        return {"success": True, "status": "stopped"}

    # ── main loop ────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        logger.info("Autopilot queue preprocessor started")
        while not self._stop:
            try:
                did_work = await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Queue preprocessor cycle failed")
                self.stats["lastError"] = str(exc)[:300]
                self._persist_stats()
                did_work = False
            # A cycle that scored postings should come straight back for more;
            # an idle one backs off so it is not spinning on the database.
            await asyncio.sleep(1.0 if did_work else IDLE_CYCLE_SECONDS)
        logger.info("Autopilot queue preprocessor stopped")

    async def _cycle(self) -> bool:
        self.stats["cycles"] = int(self.stats.get("cycles", 0)) + 1
        did_work = False

        await self._maybe_start_scrape()
        # Every stage below is synchronous and DB-bound: each one walks the full
        # autopilot-job and discovered-job tables (hundreds of rows and thousands
        # respectively) and writes rows back one flush at a time. Awaiting them
        # inline blocked the API's event loop for seconds at a time, and the loop
        # they starved included the Autopilot runner's own continuation — a job
        # whose browser submission had already been confirmed by the ATS would
        # sit unfinished, its run stuck at RUNNING and its submissionEvidence,
        # answers and SUBMITTED checkpoint never written, because the coroutine
        # that records them could not be scheduled. Hand them to a worker thread
        # instead; session_scope() builds a fresh Session per call, so each one
        # is safe off the loop.
        did_work |= await asyncio.to_thread(self._ingest_scraper_snapshot) > 0

        scored = await self._score_pending_jobs()
        did_work |= scored > 0

        enqueued = await asyncio.to_thread(self._enqueue_scored_jobs)
        did_work |= enqueued > 0

        # Applications the user finished by hand announce themselves by their
        # confirmation email, so they can mark themselves submitted instead of
        # waiting for the user to remember to. IMAP-bound, so it runs on a
        # worker thread and only every so often — the inbox is not going to
        # change between cycles that are seconds apart.
        if self.stats["cycles"] % RECONCILE_EVERY_N_CYCLES == 0:
            try:
                from app.services.application_assistant.manual_submission_reconciler import (
                    reconcile_manual_submissions,
                )

                result = await asyncio.to_thread(reconcile_manual_submissions)
                marked = int(result.get("marked") or 0)
                if marked:
                    self.stats["manualSubmissionsDetected"] = (
                        int(self.stats.get("manualSubmissionsDetected", 0)) + marked
                    )
                    did_work = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Manual-submission reconcile failed: %s", exc)

        did_work |= await asyncio.to_thread(self._sync_queue_match_scores) > 0
        await asyncio.to_thread(self._rerank_pending_queue)

        self.stats["lastCycleAt"] = now_iso()
        self._persist_stats()
        return did_work

    # ── pipeline stages ──────────────────────────────────────────────────────

    def _application_in_flight(self) -> bool:
        """True while Autopilot has a job genuinely open in an employer form.

        Freshness matters: a run killed mid-submission leaves an orphaned row
        stuck at ``APPLYING`` indefinitely. Counting one of those would pause
        queue preparation forever, so a row only counts while it is still being
        written to.
        """
        try:
            now = datetime.now(timezone.utc)
            with session_scope() as db:
                for job in list_autopilot_jobs(db):
                    if job.get("status") != AutopilotJobStatus.APPLYING.value:
                        continue
                    stamp = job.get("updatedAt") or job.get("lockedAt") or ""
                    try:
                        seen = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if (now - seen).total_seconds() <= APPLYING_FRESHNESS_SECONDS:
                        return True
            return False
        except Exception:
            return False

    async def _maybe_start_scrape(self) -> None:
        """Kick the job scraper when its last run is stale.

        Fire-and-forget: ``start_scrape_background`` owns its own task, writes
        into the scraper snapshot as batches land, and refuses politely when a
        scrape is already running.
        """
        if time.monotonic() - self._last_scrape_at < SCRAPE_INTERVAL_SECONDS:
            return
        self._last_scrape_at = time.monotonic()
        try:
            from app.services.job_discover import store as jd_store

            result = await jd_store.start_scrape_background(hours=336, roles="swe", mode="ats")
            if result.get("success"):
                self.stats["lastScrapeStartedAt"] = now_iso()
                logger.info("Queue preprocessor triggered a background job scrape")
        except Exception as exc:
            logger.warning("Could not start background scrape: %s", exc)

    def _ingest_scraper_snapshot(self) -> int:
        """Copy new scraper results into ``aa_discovered_job``.

        This is the dedupe boundary between the scraper index and Autopilot's
        own discovered-job table: the aa id is derived from the scraper id, so
        re-ingesting the same posting updates one row instead of adding another.
        """
        from app.services.application_assistant.scraper_import import scraper_job_to_aa_job
        from app.services.job_discover import store as jd_store

        added = 0
        with session_scope() as db:
            snapshot = jd_store.get_snapshot(db)
            scraper_jobs = [j for j in (snapshot.get("jobs") or []) if j.get("id")]
            self.stats["scraperSnapshotSize"] = len(scraper_jobs)
            if not scraper_jobs:
                return 0

            known_ids = {j.get("id") for j in list_discovered_jobs(db, active_only=False, exclude_demo=False)}
            for scraper_job in scraper_jobs:
                try:
                    aa_job = scraper_job_to_aa_job(scraper_job)
                except Exception:
                    continue
                if aa_job["id"] in known_ids:
                    continue
                if not aa_job.get("applicationUrl"):
                    continue
                aa_job["dateDiscovered"] = now_iso()
                # The scraper's own snapshot (see sources/base.py's ScrapedJob.
                # to_dict) never had "postedAt"/"datePosted" keys - only
                # "first_published" and "updated_at"/"updatedAt" - so this was
                # always writing "" regardless of what the source actually
                # reported, silently disabling freshness-based queue ordering
                # for every posting from every source. first_published is the
                # real "when the employer posted this" signal where a source
                # supplies it; updated_at is the next-best real signal (some
                # ATS APIs only expose a last-modified timestamp). Left blank
                # rather than defaulting to discovery time - a job we only
                # just found is not the same claim as a job that was actually
                # posted today, and posting_recency_bonus already treats a
                # blank datePosted as "no bonus" rather than guessing.
                aa_job["datePosted"] = scraper_job.get("first_published") or scraper_job.get("updated_at") or scraper_job.get("updatedAt") or ""
                upsert_discovered_job(db, aa_job)
                known_ids.add(aa_job["id"])
                added += 1

        if added:
            self.stats["scraperAdditions"] = int(self.stats.get("scraperAdditions", 0)) + added
            logger.info("Queue preprocessor ingested %d new scraper postings", added)
        return added

    def _eligible_unscored(self) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        """Discovered postings that pass the hard filters and have no Mistral score yet.

        ``allowDuplicates`` is on deliberately. The hard filters reject a
        posting that is already sitting in the queue as a duplicate, which would
        otherwise mean the rows *at the head of the queue* are the only ones
        never scored by Mistral. Deduping still happens — at enqueue time, in
        ``_enqueue_scored_jobs`` — so nothing is queued twice.
        """
        with session_scope() as db:
            profile, documents, accomplishments = load_match_context(db)
            existing_autopilot = list_autopilot_jobs(db)
            discovered = list_discovered_jobs(db, active_only=True, exclude_demo=True)

        self.stats["jobsDiscovered"] = len(discovered)

        queued_job_ids = {
            j.get("jobId") for j in existing_autopilot
            if j.get("status") == AutopilotJobStatus.QUEUED.value
        }

        rejected = 0
        pending: list[dict[str, Any]] = []
        for job in discovered:
            if isinstance(job.get("mistralMatch"), dict):
                continue
            passed, _reason = evaluate_hard_filters(
                job, profile, existing_autopilot, {"allowDuplicates": True}
            )
            if not passed:
                rejected += 1
                continue
            pending.append(job)

        self.stats["jobsRejectedByFilters"] = rejected
        # Postings already waiting in the queue are scored first — they are the
        # ones about to be applied to, so their ranking has to be the real
        # Mistral one before anything else gets attention. Within each group,
        # the highest tier goes first.
        pending.sort(
            key=lambda j: (j.get("id") in queued_job_ids, queue_priority_score(j)),
            reverse=True,
        )
        return pending, profile, documents, accomplishments

    async def _score_pending_jobs(self) -> int:
        if not LOCAL_LLM_ENABLED:
            self.stats["matchModel"] = "disabled (CAREEROS_LOCAL_LLM=off)"
            return 0
        pending, profile, documents, accomplishments = self._eligible_unscored()
        if not pending:
            return 0

        # Match scoring and resume tailoring are the same local 7B model on one
        # 8GB GPU. Sharing it cost a real submission: a scoring call in flight
        # pushed Coupang's tailoring past its 120s budget, the run fell back to
        # template wording, and the tailored resume the application was supposed
        # to carry never got generated. So scoring — and only scoring — steps
        # aside while a job is actually in an employer form. Everything else in
        # the pipeline (scrape, ingest, dedupe, filter, enqueue, re-rank) keeps
        # running, which is what "keep preparing future jobs" actually needs.
        if self._application_in_flight():
            self.stats["yieldingToApplication"] = True
            return 0
        self.stats["yieldingToApplication"] = False

        # Scored one at a time with the in-flight check repeated between jobs.
        # Checking once per cycle was not enough: a batch of six takes minutes,
        # so an application starting mid-batch kept competing with scoring for
        # the same GPU — measured as jd_resume_match latency rising from ~11s to
        # 50-85s, and one resume-tailoring call timing out into the fallback.
        batch = pending[:SCORE_BATCH_SIZE]
        concurrency = SCORE_CONCURRENCY
        client = build_mistral_match_client()
        self.stats["matchModel"] = client.model
        matches = await score_jobs_against_resume(
            batch,
            profile,
            documents=documents,
            accomplishments=accomplishments,
            concurrency=concurrency,
            client=client,
            should_continue=lambda: not self._application_in_flight(),
        )
        if not matches:
            return 0

        with session_scope() as db:
            for job in batch:
                match = matches.get(str(job.get("id")))
                if not match:
                    continue
                upsert_discovered_job(db, {
                    **job,
                    "mistralMatch": match,
                    "matchScore": match["matchScore"],
                    "matchReason": match["matchReason"],
                    "keyMatchingSkills": match["keyMatchingSkills"],
                    "missingSkills": match["missingSkills"],
                    "matchMethod": match["matchMethod"],
                    "matchScoredAt": now_iso(),
                })

        self.stats["jobsPreprocessed"] = int(self.stats.get("jobsPreprocessed", 0)) + len(matches)
        logger.info("Queue preprocessor scored %d posting(s) with %s", len(matches), client.model)
        return len(matches)

    def _enqueue_scored_jobs(self) -> int:
        """Move Mistral-scored, filter-passing postings into the QUEUED state.

        No size limit is applied — ``filter_and_rank_jobs`` is called without a
        ``maxApplicationsPerRun``, so the queue grows to hold every eligible
        posting the pipeline has prepared.
        """
        with session_scope() as db:
            profile = get_kv(db, "profile") or {}
            documents = get_kv(db, "documents") or {}
            from app.db.store import list_entities
            accomplishments = list_entities(db, "accomplishment")
            existing_autopilot = list_autopilot_jobs(db)
            discovered = list_discovered_jobs(db, active_only=True, exclude_demo=True)

        queued_now = sum(
            1 for j in existing_autopilot if j.get("status") == AutopilotJobStatus.QUEUED.value
        )

        # Hysteresis between the two watermarks: once intake pauses at
        # HIGH_QUEUE_WATERMARK it stays paused until depth falls back to
        # LOW_QUEUE_WATERMARK, rather than flapping on/off around a single
        # threshold every cycle.
        was_replenishing = bool(self.stats.get("queueReplenishing", True))
        if queued_now <= LOW_QUEUE_WATERMARK:
            replenishing = True
        elif queued_now >= HIGH_QUEUE_WATERMARK:
            replenishing = False
        else:
            replenishing = was_replenishing
        self.stats["queueReplenishing"] = replenishing
        self.stats["queueBelowLowWatermark"] = queued_now <= LOW_QUEUE_WATERMARK

        headroom = (HIGH_QUEUE_WATERMARK - queued_now) if replenishing else 0
        if headroom <= 0:
            # Topped up to the high watermark. Existing rows stay untouched —
            # the watermark throttles intake, it does not evict work that is
            # already prepared.
            self.stats["queueSize"] = queued_now
            self.stats["queueAtCapacity"] = True
            return 0
        self.stats["queueAtCapacity"] = False

        # Requiring a Mistral score before a posting could be queued starves
        # this path to nothing while LOCAL_LLM_ENABLED is off (see module
        # docstring / CAREEROS_LOCAL_LLM=off) - no posting will ever get a
        # mistralMatch, so the queue would sit empty forever. With the model
        # off there is no GPU contention risk left to protect against, so use
        # filter_and_rank_jobs's deterministic heuristic path directly for
        # every unqueued posting.
        #
        # (An earlier attempt to do this unconditionally - while the model
        # was still on - hit a real O(n x m) duplicate-check blowup that hung
        # the whole server; that was the *duplicate check*, not the heuristic
        # matching itself, and is fixed below with an O(1) in-memory index.
        # Kept this path Mistral-gated whenever the model is actually on, to
        # match the proven-stable behavior and not reopen that investigation
        # while it's unresolved.)
        already_queued_job_ids = {j.get("jobId") for j in existing_autopilot}
        if LOCAL_LLM_ENABLED:
            scored = [j for j in discovered if isinstance(j.get("mistralMatch"), dict)]
            candidates = [j for j in scored if j.get("id") not in already_queued_job_ids]
        else:
            candidates = [j for j in discovered if j.get("id") not in already_queued_job_ids]
        if not candidates:
            self.stats["queueSize"] = sum(
                1 for j in existing_autopilot if j.get("status") == AutopilotJobStatus.QUEUED.value
            )
            return 0

        precomputed = {
            str(j["id"]): j["mistralMatch"] for j in candidates if isinstance(j.get("mistralMatch"), dict)
        }
        ranked = filter_and_rank_jobs(
            existing_autopilot, candidates, profile, {}, precomputed_matches=precomputed,
            documents=documents, accomplishments=accomplishments,
        )

        enqueued = 0
        deduped = 0
        resolved_aggregators = 0

        # Resolve aggregator listings to the employer's own board before
        # anything is written.
        #
        # A Himalayas (or similar) link is a republished posting, not an
        # application form, so queuing one guarantees the job can never be
        # submitted - and Himalayas in particular sits behind a challenge that
        # the automation must not and will not try to pass. The employer's board
        # publishes the same posting through a public API, so the listing is
        # looked up at the source and the real URL is what gets stored.
        #
        # Doing it here, at the single point where discovered postings become
        # queued jobs, means every future scrape is filtered through it without
        # each caller having to remember. It also has to happen BEFORE the
        # duplicate check below: the dedupe key is built from the URL, so
        # resolving afterwards would let the same posting in twice, once under
        # each link.
        from app.services.job_discover.aggregator_resolve import (
            is_aggregator_url,
            resolve_aggregator_url,
        )

        aggregator_rows = [
            r for r in ranked
            if is_aggregator_url(str(r.get("applicationUrl") or r.get("listingUrl") or ""))
        ]
        if aggregator_rows:
            def _resolve_row(row: dict[str, Any]) -> None:
                source_url = str(row.get("applicationUrl") or row.get("listingUrl") or "")
                found = resolve_aggregator_url(
                    source_url,
                    company_name=str(row.get("company") or ""),
                    title=str(row.get("title") or ""),
                )
                if found:
                    row["aggregatorUrl"] = source_url
                    row["applicationUrl"] = found["applicationUrl"]
                    if found.get("title"):
                        row["title"] = found["title"]

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(_resolve_row, aggregator_rows))
            resolved_aggregators = sum(1 for r in aggregator_rows if r.get("aggregatorUrl"))
            logger.info(
                "Resolved %d of %d aggregator listings to an employer board.",
                resolved_aggregators, len(aggregator_rows),
            )
            self.stats["aggregatorsResolved"] = (
                self.stats.get("aggregatorsResolved", 0) + resolved_aggregators
            )

        # Aggregator listings that resolve_aggregator_url could not match to
        # the employer's own board (most of them - only a small minority
        # resolve) would otherwise get queued with the original aggregator
        # URL and fail identically once actually attempted: "No application
        # form on the posting page". That is correct behavior at attempt
        # time, but queuing them at all just delays a known-dead-end to a
        # live batch slot instead of skipping it here where the same
        # resolution attempt already just ran. Mirrors how duplicates are
        # skipped below rather than queued and failed later.
        unresolved_aggregator_ids = {
            id(r) for r in aggregator_rows if not r.get("aggregatorUrl")
        } if aggregator_rows else set()
        unresolved_skipped = 0

        # is_duplicate_application() re-queries and full-scans every autopilot
        # job on each call - cheap for the small number of candidates this
        # path normally sees, but still unnecessary work per candidate.
        # `existing_autopilot` is already loaded above, so the same
        # canonical-URL / composite-key comparison is built as two sets once
        # instead, and updated as rows are added so a duplicate within this
        # same batch is still caught exactly as the DB-backed check would
        # have caught it.
        #
        # No status is excluded: a job the operator already reached a verdict
        # on - SUBMITTED, in review, MANUAL_REVIEW, INELIGIBLE, or SKIPPED -
        # must not resurface as a "new" discovery next cycle just because the
        # scraper saw the same posting again. Refill idempotency is defined
        # against every already-processed job, skipped ones included.
        EXCLUDED_DUP_STATUSES: set[str] = set()
        seen_url_keys: set[str] = set()
        seen_composite_keys: set[str] = set()
        for existing in existing_autopilot:
            if (existing.get("status") or "").upper() in EXCLUDED_DUP_STATUSES:
                continue
            u = _canonical_url_key(existing.get("applicationUrl") or "")
            if u:
                seen_url_keys.add(u)
            seen_composite_keys.add(_composite_job_key(
                existing.get("company") or "", existing.get("title") or "", existing.get("applicationUrl") or "",
            ))

        with session_scope() as db:
            for r in ranked:
                if id(r) in unresolved_aggregator_ids:
                    unresolved_skipped += 1
                    continue
                company = r.get("company") or ""
                title = r.get("title") or ""
                url = r.get("applicationUrl") or r.get("listingUrl") or ""
                url_key = _canonical_url_key(url)
                composite_key = _composite_job_key(company, title, url)
                if (url_key and url_key in seen_url_keys) or composite_key in seen_composite_keys:
                    deduped += 1
                    continue
                if url_key:
                    seen_url_keys.add(url_key)
                seen_composite_keys.add(composite_key)
                save_autopilot_job(db, {
                    "id": new_id("apjob_"),
                    "jobId": r.get("id") or new_id("job_"),
                    "company": company,
                    "title": title,
                    "location": r.get("location", ""),
                    "applicationUrl": url,
                    # Keep where it came from, so a resolved job can still be
                    # traced back to the listing that produced it.
                    "aggregatorUrl": r.get("aggregatorUrl"),
                    "status": AutopilotJobStatus.QUEUED.value,
                    "matchScore": r.get("matchScore", 0.0),
                    "matchReason": r.get("matchReason", ""),
                    "keyMatchingSkills": r.get("keyMatchingSkills", []),
                    "missingSkills": r.get("missingSkills", []),
                    "matchMethod": r.get("matchMethod", ""),
                    "matchModel": r.get("matchModel", ""),
                    "matchReasons": r.get("matchReasons", []),
                    "queuePriority": r.get("queuePriority", 0.0),
                    "discoveredAt": now_iso(),
                    "queuedAt": now_iso(),
                })
                enqueued += 1
                if enqueued >= headroom:
                    logger.info(
                        "Queue preprocessor reached the high watermark (%d); pausing intake",
                        HIGH_QUEUE_WATERMARK,
                    )
                    break

        if deduped:
            self.stats["jobsDeduped"] = int(self.stats.get("jobsDeduped", 0)) + deduped
        if unresolved_skipped:
            self.stats["jobsUnresolvedAggregatorSkipped"] = (
                int(self.stats.get("jobsUnresolvedAggregatorSkipped", 0)) + unresolved_skipped
            )
            logger.info(
                "Queue preprocessor skipped %d unresolvable aggregator listing(s) "
                "(no employer board match) instead of queuing them to fail later",
                unresolved_skipped,
            )
        if enqueued:
            self.stats["jobsEnqueued"] = int(self.stats.get("jobsEnqueued", 0)) + enqueued
            logger.info("Queue preprocessor enqueued %d new posting(s)", enqueued)
        return enqueued

    def _sync_queue_match_scores(self) -> int:
        """Copy the Mistral match onto queue rows still carrying an older score.

        Rows queued before this pipeline existed (or refilled by the runner's
        own catch-up path) hold a keyword-heuristic ``matchScore``. Once the
        posting they point at has been scored by Mistral, the queue row has to
        pick that up or the ordering at the head of the queue is still the old
        heuristic ranking. Only ``QUEUED`` rows are rewritten — a job that has
        already been applied to keeps the score it was submitted under.
        """
        with session_scope() as db:
            queued = [
                j for j in list_autopilot_jobs(db)
                if j.get("status") == AutopilotJobStatus.QUEUED.value
                and j.get("matchMethod") != "ollama-local"
            ]
            if not queued:
                return 0
            discovered_by_id = {
                j.get("id"): j
                for j in list_discovered_jobs(db, active_only=False, exclude_demo=False)
            }

            updated = 0
            for job in queued:
                source = discovered_by_id.get(job.get("jobId"))
                match = source.get("mistralMatch") if isinstance(source, dict) else None
                if not isinstance(match, dict):
                    continue
                job.update({
                    "matchScore": match["matchScore"],
                    "matchReason": match["matchReason"],
                    "keyMatchingSkills": match["keyMatchingSkills"],
                    "missingSkills": match["missingSkills"],
                    "matchMethod": match["matchMethod"],
                    "matchModel": match.get("matchModel", ""),
                    "matchReasons": match["keyMatchingSkills"][:8],
                })
                job["queuePriority"] = queue_priority_score(job)
                save_autopilot_job(db, job)
                updated += 1

        if updated:
            logger.info("Queue preprocessor re-scored %d queued row(s) with Mistral", updated)
        return updated

    def _rerank_pending_queue(self) -> int:
        """Recompute every waiting job's queue priority.

        A posting discovered five minutes ago that outranks what is already
        waiting has to be able to overtake it, so the ordering key is refreshed
        on the rows themselves rather than only at insert time. Only ``QUEUED``
        rows are touched: anything claimed, applying, or terminal is left alone.
        """
        changed = 0
        with session_scope() as db:
            queued = [
                j for j in list_autopilot_jobs(db)
                if j.get("status") == AutopilotJobStatus.QUEUED.value
            ]
            ordered = sorted(queued, key=queue_priority_score, reverse=True)
            for position, job in enumerate(ordered):
                priority = queue_priority_score(job)
                if job.get("queuePriority") == priority and job.get("queuePosition") == position:
                    continue
                job["queuePriority"] = priority
                job["queuePosition"] = position
                save_autopilot_job(db, job)
                changed += 1
            self.stats["queueSize"] = len(queued)
        return changed

    # ── stats ────────────────────────────────────────────────────────────────

    def _persist_stats(self) -> None:
        self.stats["running"] = self.is_running()
        try:
            with session_scope() as db:
                set_kv(db, STATS_KV_KEY, self.stats)
        except Exception:
            logger.debug("Could not persist preprocessor stats", exc_info=True)


def get_preprocessor() -> QueuePreprocessor:
    return QueuePreprocessor.get_instance()


__all__ = [
    "QueuePreprocessor",
    "get_preprocessor",
    "get_stats",
    "STATS_KV_KEY",
]
