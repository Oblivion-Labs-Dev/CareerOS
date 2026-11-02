# CareerOS Web — Next.js dev server on :3000.
#
# Built from the repository root, not from frontend/, because this is a pnpm
# workspace: `@career-os/web` depends on `@career-os/core` and `@career-os/ui`
# through `workspace:*`, and both publish compiled `dist/` output via tsup. They
# have to be installed and built inside the image or the app cannot resolve its
# own imports.
#
# This targets development (`next dev`), which is what the task asks for —
# hot reload with the source bind-mounted. A production image would add a
# `next build` stage and run `next start`; that is deliberately out of scope.
# Node 24, matching the local toolchain (v24.19.0). Not Node 20: pnpm 11
# requires the `node:sqlite` built-in, which does not exist before 22.5, and the
# install dies with ERR_UNKNOWN_BUILTIN_MODULE. The root package.json says
# `engines: node >=20`, which is true of the application but not of the package
# manager the lockfile was written by.
FROM node:24-bookworm-slim

ENV NODE_ENV=development \
    NEXT_TELEMETRY_DISABLED=1 \
    # Polling is what makes hot reload survive a bind mount from a Windows host
    # into the Linux VM — inotify events do not cross that boundary reliably.
    WATCHPACK_POLLING=true \
    CHOKIDAR_USEPOLLING=true

# pnpm 11 via corepack, matching the local toolchain and lockfileVersion 9.0.
RUN corepack enable && corepack prepare pnpm@11.9.0 --activate

WORKDIR /app

# Manifests and the lockfile first so dependency installation caches
# independently of source edits. Every workspace member's package.json is needed
# for pnpm to resolve the workspace graph.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY frontend/package.json ./frontend/
COPY extension/package.json ./extension/
COPY packages/career-core/package.json ./packages/career-core/
COPY packages/career-ui/package.json ./packages/career-ui/

# --ignore-scripts keeps the extension's postinstall hooks out of this image.
RUN pnpm install --frozen-lockfile --ignore-scripts

# The shared packages, then the app. Source for frontend/ is bind-mounted over
# by compose, but the built dist/ of the packages must live in the image because
# the mount would otherwise shadow nothing and leave them unbuilt.
COPY packages ./packages
RUN pnpm --filter @career-os/core --filter @career-os/ui run build

# frontend/(app)/resume-corpus/corpus-seed-data.ts imports this by relative path
# into the repository root, so it has to exist at /app/data or the page fails.
COPY data/resume-corpus-initial.json /app/data/

COPY frontend ./frontend

WORKDIR /app/frontend

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD node -e "require('http').get('http://127.0.0.1:3000/',r=>process.exit(r.statusCode<500?0:1)).on('error',()=>process.exit(1))"

# Binds 0.0.0.0 so the port is reachable from the host.
CMD ["pnpm", "exec", "next", "dev", "--hostname", "0.0.0.0", "--port", "3000"]
