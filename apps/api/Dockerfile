# CareerOS API — FastAPI on :4000, with Playwright and Chromium in the same image.
#
# Why Playwright lives here rather than in its own service:
#
# The API drives the browser in-process. `browser_runner.py` owns a dedicated
# event-loop thread and hands Playwright objects straight to
# `playwright_autopilot_executor.py`; there is no wire protocol between them.
# The assisted-fill path calls `chromium.launch_persistent_context(...,
# channel="chrome")`, and a persistent context cannot be driven over
# Playwright's `connect()` — that API only returns ordinary browser instances.
# Splitting the browser into its own container would therefore mean inventing an
# RPC layer, which the task forbids, or silently dropping assisted fill under
# Docker, which would make container behaviour differ from local behaviour.
#
# So the browser ships next to the code that launches it. The official Playwright
# image is the supported way to get Chromium plus its system libraries, and the
# tag is pinned to the exact `playwright` version in requirements so the driver
# and the browser build can never drift apart.
FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Hugging Face cache for the resume-ranking embeddings. Mounted as a volume
    # by compose: semantic.py loads with local_files_only=True and degrades to
    # BM25 when the weights are absent, so an unmounted cache is a quality
    # regression rather than a crash — worth persisting deliberately.
    HF_HOME=/models \
    SENTENCE_TRANSFORMERS_HOME=/models

WORKDIR /app/apps/api

# Dependencies first, so edits to application code do not reinstall the world.
# PyTorch arrives via sentence-transformers and dominates both the image size
# and the build time.
# ── Size controls ────────────────────────────────────────────────────────────
# The default build was 14.2 GB, and almost none of that was CareerOS. Installing
# sentence-transformers pulls torch (555 MB) plus ~2.2 GB of nvidia_* CUDA wheels
# and triton (248 MB) — none of which can ever run here, because `semantic.py`
# loads its model with device="cpu" and no GPU is exposed to the container.
#
#   TORCH_VARIANT=cpu       PyTorch from the CPU-only wheel index. No CUDA.
#   TORCH_VARIANT=default   Whatever PyPI resolves, CUDA included.
#   INSTALL_ML=true|false   false skips sentence-transformers entirely.
#   INSTALL_DEV=true|false  pytest/ruff/mypy for running the suite in-container.
ARG TORCH_VARIANT=cpu
ARG INSTALL_ML=true
ARG INSTALL_DEV=true

COPY apps/api/requirements.txt ./requirements.txt
COPY apps/api/requirements-dev.txt ./requirements-dev.txt

# CPU-only torch goes in first so that when pip resolves sentence-transformers
# below, the torch requirement is already satisfied and the CUDA build is never
# considered. requirements.txt does not pin torch, so this is a substitution
# rather than a conflict.
RUN if [ "$INSTALL_ML" = "true" ] && [ "$TORCH_VARIANT" = "cpu" ]; then \
        python -m pip install --no-cache-dir torch \
            --index-url https://download.pytorch.org/whl/cpu ; \
    fi

# With INSTALL_ML=false the one heavy line is filtered out of the existing
# requirements file rather than a second requirements file being invented.
# semantic.py already degrades to BM25 + skill-taxonomy matching when the
# package or its cached weights are missing — that is documented behaviour in
# the module, not a failure mode introduced here. Resume ranking gets worse;
# nothing breaks.
RUN if [ "$INSTALL_ML" = "true" ]; then \
        python -m pip install --no-cache-dir -r requirements.txt ; \
    else \
        grep -viE '^[[:space:]]*sentence-transformers' requirements.txt > /tmp/req-noml.txt && \
        python -m pip install --no-cache-dir -r /tmp/req-noml.txt ; \
    fi

# Dev tooling, so the suite runs where the code runs. requirements-dev.txt
# starts with `-r requirements.txt`, so it reuses the existing dependency
# configuration; by this point that is already satisfied and only the small
# tools are fetched.
RUN if [ "$INSTALL_DEV" = "true" ]; then \
        python -m pip install --no-cache-dir pytest ruff mypy types-PyYAML ; \
    fi

# The base image already ships browsers for the pwuser account. Chromium is what
# the autopilot path launches (`chromium.launch`), so only that is installed
# here; `channel="chrome"` from the assisted path needs real Google Chrome, which
# is a headed flow and is documented as a local-only workflow in docs/docker.md.
RUN playwright install chromium

# Repository-root seed data. `store.py` resolves the resume corpus and
# `story_index.py` the interview story corpus as parents[4]/data/..., i.e.
# /app/data — outside the API's own tree. Without these the story index has no
# corpus, which silently degrades the evidence retrieval that resume tailoring
# is built on.
COPY data/resume-corpus-initial.json data/interview-story-corpus.json /app/data/

# Application code. Bind-mounted over by compose in development, so this layer
# exists to make the image runnable on its own.
COPY apps/api ./

# The data directory is always a mount. Creating it here means the container
# still starts (with an empty database) when someone runs the image without
# compose, rather than failing on a missing path.
RUN mkdir -p data/application_assistant/screenshots \
             data/application_assistant/tailored_resumes \
             data/application_assistant/traces \
             data/application_assistant/browser_profile \
             data/logs \
    && chmod -R 777 data /models 2>/dev/null || true

EXPOSE 4000

# Chromium cannot run as root without --no-sandbox, and the base image provides
# an unprivileged account precisely for this.
USER pwuser

# Hits the same endpoint the local workflow checks. Generous start period: the
# first request imports torch and sentence-transformers.
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:4000/health', timeout=4).status==200 else 1)"

# One worker, always. `main.py` refuses to start with more, because Autopilot
# state — browser sessions, task handles, the scrape task, the read cache — is
# process-local. Reload is off by default; compose turns it on for development.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4000"]
