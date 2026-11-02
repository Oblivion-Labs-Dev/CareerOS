import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import path from "node:path";
import { readdirSync, statSync } from "node:fs";

let worker: ChildProcessWithoutNullStreams | null = null;
let idle: ReturnType<typeof setTimeout> | null = null;
let loadedVersion = "";

/** One bounded CPU worker. Reuse cached rankings between previews, then release
 * the process and its model memory after two minutes without a request. */
export function composeInLocalWorker(python: string, apiRoot: string, payload: unknown, signal: AbortSignal): Promise<string> {
  if (idle) clearTimeout(idle);
  const serviceRoot = path.join(apiRoot, "app/services/resume_intelligence");
  const version = readdirSync(serviceRoot).filter(name => name.endsWith(".py")).map(name => `${name}:${statSync(path.join(serviceRoot, name)).mtimeMs}`).join("|");
  if (worker && loadedVersion !== version) { worker.kill(); worker = null; }
  if (!worker || worker.killed || worker.exitCode !== null) {
    loadedVersion = version;
    worker = spawn(python, [path.join(apiRoot, "scripts/resume_studio_worker.py")], {
      cwd: apiRoot, windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: "utf-8", HF_HUB_OFFLINE: "1" },
      stdio: ["pipe", "pipe", "pipe"],
    });
    worker.stdout.setEncoding("utf-8");
    worker.stderr.resume(); // Drain library diagnostics without logging profile data.
    worker.stdin.on("error", () => { /* handled by the per-request exit listener */ });
  }
  const child = worker;
  return new Promise((resolve, reject) => {
    let output = "";
    let done = false;
    const timeout = setTimeout(() => fail(new Error("Local resume generation timed out")), 55000);
    function cleanup() {
      clearTimeout(timeout); signal.removeEventListener("abort", abort);
      child.stdout.off("data", receive); child.off("error", fail); child.off("exit", exited);
    }
    function fail(error: Error) {
      if (done) return; done = true; cleanup(); child.kill();
      if (worker === child) worker = null;
      reject(error);
    }
    function abort() { fail(new Error("Resume generation cancelled")); }
    function exited() { fail(new Error("Local resume worker stopped")); }
    function receive(chunk: string) {
      output += chunk;
      if (output.length > 12 * 1024 * 1024) { fail(new Error("Resume output exceeded its size limit")); return; }
      const end = output.indexOf("\n");
      if (end < 0) return;
      done = true; cleanup();
      idle = setTimeout(() => { child.kill(); if (worker === child) worker = null; }, 120000);
      idle.unref();
      resolve(output.slice(0, end));
    }
    child.stdout.on("data", receive); child.once("error", fail); child.once("exit", exited);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
    else child.stdin.write(JSON.stringify(payload) + "\n");
  });
}
