#!/usr/bin/env node
// GitHub/npx bootstrap. The Python installer owns client detection and config updates.
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const options = process.argv.slice(2);
const windows = process.platform === "win32";
const suffix = windows ? ".exe" : "";
const version = JSON.parse(readFileSync(join(root, "package.json"), "utf8")).version;

function run(command, args, { capture = false, env = process.env, cwd } = {}) {
  const result = spawnSync(command, args, {
    stdio: capture ? ["inherit", "pipe", "inherit"] : "inherit",
    encoding: "utf8", env, cwd, windowsHide: true, shell: false,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} exited with status ${result.status}`);
  return result.stdout?.trim();
}

async function findUv() {
  const base = windows
    ? process.env.LOCALAPPDATA || join(homedir(), "AppData", "Local")
    : process.platform === "darwin"
      ? join(homedir(), "Library", "Application Support")
      : process.env.XDG_DATA_HOME || join(homedir(), ".local", "share");
  const bin = resolve(base, "font-design-mcp", "bin");
  const bundled = join(bin, `uv${suffix}`);
  for (const candidate of ["uv", bundled, join(homedir(), ".local", "bin", `uv${suffix}`)]) {
    if (spawnSync(candidate, ["--version"], { stdio: "ignore", windowsHide: true }).status === 0) {
      return candidate;
    }
  }
  console.log("Installing uv (Python environment manager)...");
  const folder = mkdtempSync(join(tmpdir(), "font-design-uv-"));
  try {
    const name = windows ? "install.ps1" : "install.sh";
    const response = await fetch(`https://astral.sh/uv/0.12.10/${name}`, {
      signal: AbortSignal.timeout(60000),
    });
    if (!response.ok) throw new Error(`uv installer download failed: HTTP ${response.status}`);
    const script = join(folder, name);
    writeFileSync(script, await response.text());
    const env = { ...process.env, UV_UNMANAGED_INSTALL: bin };
    if (windows) {
      // PowerShell 7 module paths can break the Windows PowerShell 5 bootstrap.
      env.PSModulePath = join(process.env.SystemRoot || "C:\\Windows", "System32", "WindowsPowerShell", "v1.0", "Modules");
      run("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script], { env });
    } else {
      run("/bin/sh", [script], { env });
    }
    if (!existsSync(bundled)) throw new Error("uv installation did not produce an executable");
    return bundled;
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
}

async function main() {
  if (options.includes("--help") || options.includes("-h")) {
    console.log(`Font Design MCP ${version}
Usage: npx --yes github:Kydaix/Font-Design-MCP [options]

  --clients codex claude-code cursor  Choose one or more clients
  --workspace PATH                   Directory for font projects
  --yes                              Configure all detected clients
  --dry-run                          Install runtime, preview client changes only

Without options, detects clients and prompts for your selection.
Installs Python 3.13 and the MCP in a persistent uv tool environment.
Existing client files are backed up before changes. No PyPI publication required.`);
    return;
  }
  if (!["win32", "darwin", "linux"].includes(process.platform)) {
    throw new Error(`Unsupported platform: ${process.platform}`);
  }
  const uv = await findUv();
  console.log(`Installing Font Design MCP ${version} from GitHub sources...`);
  run(uv, ["tool", "install", "--python", "3.13", "--reinstall-package", "font-design-mcp",
    "--constraints", "requirements.lock", `font-design-mcp @ ${pathToFileURL(root).href}`], { cwd: root });
  const bin = run(uv, ["tool", "dir", "--bin"], { capture: true });
  run(join(bin, `font-design-mcp${suffix}`), ["install", ...options]);
}

main().catch(error => {
  console.error(`Installation failed: ${error.message}`);
  process.exitCode = 1;
});
