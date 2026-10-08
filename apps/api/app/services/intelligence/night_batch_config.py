"""Night Batch continuous-operation configuration.

Replaces the fixed 50-job queue cap with configurable high/low watermarks
and defines the safety guards for unattended overnight batch runs.
"""

import os

# Queue watermarks - replaces the fixed CAREEROS_MAX_QUEUE_SIZE cap.
# When queue depth drops to/below LOW, replenishment kicks in until it
# reaches HIGH again. Both are env-overridable for tuning without a redeploy.
LOW_QUEUE_WATERMARK = int(os.environ.get("CAREEROS_QUEUE_LOW_WATERMARK", "2000"))
HIGH_QUEUE_WATERMARK = int(os.environ.get("CAREEROS_QUEUE_HIGH_WATERMARK", "5000"))

# Batch operations
BATCH_SIZE = int(os.environ.get("CAREEROS_NIGHT_BATCH_SIZE", "10"))
MAX_BATCH_CONCURRENT = 1  # Strictly one application at a time via the UI.

# Safety and validation
MIN_MATCH_SCORE = int(os.environ.get("CAREEROS_MIN_MATCH_SCORE", "75"))

# Priority rules (job_filter_ranker.queue_priority_score):
# 1. Postings from the last 24 hours, then older recency bands
# 2. Senior, Forward Deployed Engineer, Principal, SDE 2, Staff, SDE 1, other
# 3. Washington State (Seattle, Bellevue, Redmond, rest of WA), then rest of the US
# 4. Freshness within the band, then resume/JD match score

# Validation guards
ENABLE_DETERMINISTIC_VALIDATION = True
ALLOW_DUPLICATES = False
ENABLE_LOG_AUDIT = True

# External confirmation
VERIFY_EXTERNAL_SUBMISSION = True

# Safety limits
MAX_FAILURES_BEFORE_REPLAN = 3  # Consecutive failures before pausing for investigation.
MAX_REPROCESS_ATTEMPTS = 5  # Max retries for a single job after a root-cause fix.

# Night Batch operation mode: "continuous" runs consecutive batches until
# stopped; "one-time" runs a single batch and stops.
OPERATION_MODE = os.environ.get("CAREEROS_NIGHT_BATCH_MODE", "continuous")
