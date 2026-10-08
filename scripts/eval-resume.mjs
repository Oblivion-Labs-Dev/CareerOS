// Runs the resume compiler evals with the API's virtualenv Python: npm run eval:resume [-- --offline] [-- --only id ...]
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const api = join(dirname(fileURLToPath(import.meta.url)), "..", "apps", "api");
const venv = process.platform === "win32" ? join(api, ".venv", "Scripts", "python.exe") : join(api, ".venv", "bin", "python");
const python = existsSync(venv) ? venv : "python";
const result = spawnSync(python, ["-m", "app.services.career_compiler.evals", ...process.argv.slice(2)], { cwd: api, stdio: "inherit" });
process.exit(result.status ?? 1);
