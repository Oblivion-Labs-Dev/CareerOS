#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const isWin = process.platform === "win32";

const result = isWin
  ? spawnSync(
      "powershell",
      [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        path.join(root, "scripts", "ci.ps1"),
      ],
      { stdio: "inherit", cwd: root, env: process.env },
    )
  : spawnSync("bash", [path.join(root, "scripts", "ci.sh")], {
      stdio: "inherit",
      cwd: root,
      env: process.env,
    });

process.exit(result.status ?? 1);
