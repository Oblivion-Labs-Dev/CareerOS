import fs from "fs";
import path from "path";

export interface ExtensionDistPathInfo {
  distPath: string;
  distReady: boolean;
}

const MANIFEST = "manifest.json";

function hasBuiltDist(dir: string): boolean {
  return fs.existsSync(path.join(dir, MANIFEST));
}

/** Resolve ApplyPilot dist folder by walking up from cwd (works without FastAPI or .env). */
export function getExtensionDistPath(): ExtensionDistPathInfo {
  const envOverride = process.env.NEXT_PUBLIC_EXTENSION_DIST_PATH?.trim();
  if (envOverride) {
    return { distPath: envOverride, distReady: hasBuiltDist(envOverride) };
  }

  const relativeCandidates = [
    path.join("apps", "extension", "dist"),
    path.join("..", "extension", "dist"),
    path.join("..", "..", "career-os", "apps", "extension", "dist"),
    path.join("career-os", "apps", "extension", "dist"),
  ];

  let dir = process.cwd();
  for (let depth = 0; depth < 12; depth++) {
    for (const relative of relativeCandidates) {
      const candidate = path.resolve(dir, relative);
      if (hasBuiltDist(candidate)) {
        return { distPath: candidate, distReady: true };
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }

  // Display best guess even before first build
  const fallback = path.resolve(process.cwd(), "..", "extension", "dist");
  return { distPath: fallback, distReady: hasBuiltDist(fallback) };
}
