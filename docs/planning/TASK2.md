# Task: Optimize CareerOS Docker Images

Optimize the CareerOS Docker setup for small, reproducible, secure images without breaking development or Playwright.

## Goals

Reduce:

* final image size
* unnecessary layers
* build context
* rebuild time
* duplicated dependencies

Preserve correctness and developer usability.

## Before Changing

Measure and record the current baseline:

* image sizes
* layer sizes
* build times
* largest layers/files
* build context size

Use this baseline to prove whether optimizations actually help.

## Optimization Requirements

### Multi-stage builds

Use separate build and runtime stages where beneficial.

Do not include compilers, build tools, caches, source artifacts, or development dependencies in runtime images unless required.

### Base images

Choose the smallest practical supported runtime image.

Prefer:

* Node slim/runtime images for Next.js
* Python slim images for FastAPI
* an official Playwright-compatible image/stage where browser system dependencies are required

Evaluate Alpine/distroless/scratch only when compatible. Do not use them simply because they are smaller.

### Next.js

Investigate Next.js standalone output so the runtime image contains only the server and required production dependencies rather than the full development dependency tree.

### FastAPI

Use a slim Python runtime.

Install dependencies without retaining package/pip caches.

Keep build-only native compilation dependencies out of the final stage.

### Playwright

Playwright/Chromium will likely be the largest image.

Optimize it independently from Web/API.

Do not install unnecessary browsers if CareerOS only uses Chromium.

Preserve all required Chromium system libraries and Playwright compatibility.

### Dockerfile efficiency

* Combine related `RUN` operations where it reduces unnecessary layers.
* Remove temporary package/cache files in the same layer that creates them.
* Copy dependency manifests before source code to maximize build cache reuse.
* Order layers from least-changing to most-changing.
* Use `.dockerignore` aggressively.
* Exclude `.git`, `.next`, virtual environments, node_modules, logs, screenshots, application evidence, browser profiles, caches, and other unnecessary build context.
* Use BuildKit cache mounts where useful for npm/pip dependency downloads.
* Pin important runtime/base versions appropriately.
* Run services as non-root where practical.

Do not combine unrelated operations merely to minimize layer count; optimize for both image size and cache effectiveness.

## Important

Do not use `scratch`, Alpine, or distroless if doing so makes Python, Node, Chromium, native libraries, debugging, or security updates unreliable.

Image size is secondary to correctness and reproducibility.

## Verification

After optimization:

1. Rebuild all images from clean state.
2. Verify Web, API, and Playwright start.
3. Verify Web → API.
4. Verify API → host MySQL.
5. Verify Ollama connectivity.
6. Verify Chromium launches and safe Playwright navigation works.
7. Run relevant tests/typecheck.
8. Compare before/after image sizes and build times.

Provide a final comparison:

| Image      | Before | After | Reduction |
| ---------- | -----: | ----: | --------: |
| Web        |        |       |           |
| API        |        |       |           |
| Playwright |        |       |           |
| Total      |        |       |           |

Also identify the largest remaining image layers and explain whether further reduction is worth the complexity.

Do not change CareerOS business behavior or submit real applications.
