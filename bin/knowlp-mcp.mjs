#!/usr/bin/env node
// knowlp-mcp launcher — MCP stdio entry point of the dsh bundle
//
// Role: locate (or bootstrap) a Python environment able to run knowlp_mcp.py,
// then hand stdio over to the Python-side MCP server. No manual pip install.
//
// Behavior:
//   1. KNOWLP_PYTHON set → use it directly (assumes the mcp SDK is installed)
//   2. otherwise use ~/.knowlp-dsh/venv (create it with python -m venv if absent,
//      and pip install mcp pyyaml — first run only, instant afterwards)
//   3. run the knowlp_mcp.py shipped inside this package with that Python, cwd = package dir
//
// Environment passthrough: KNOWLP_VAULT / KNOWLP_GRAPH_DIR / KNOWLP_SKILL_INDEX etc.
// are all forwarded unchanged to the Python child process.

import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const PKG_DIR = dirname(dirname(fileURLToPath(import.meta.url))) // npm package root
const VENV = process.env.KNOWLP_VENV || join(homedir(), '.knowlp-dsh', 'venv')

function venvPython() {
  return process.platform === 'win32'
    ? join(VENV, 'Scripts', 'python.exe')
    : join(VENV, 'bin', 'python')
}

// returns [cmd, ...preArgs] — supports launch forms with args such as `py -3`
function findPython() {
  if (process.env.KNOWLP_PYTHON) return [process.env.KNOWLP_PYTHON]

  // 1. python/python3 from PATH (normal environment)
  for (const cand of ['python', 'python3']) {
    const r = spawnSync(cand, ['-c', 'import sys'], { windowsHide: true })
    if (r.status === 0) return [cand]
  }

  // 2. previously bootstrapped venv — deterministic absolute path, independent
  //    of PATH (P0-4: when the host session's PATH has no Python dir, this is
  //    the only stable interpreter)
  if (existsSync(venvPython()) && hasMcp([venvPython()])) return [venvPython()]

  // 3. Windows: the py launcher does not depend on PATH (py.exe lives in C:\Windows or at registry level)
  if (process.platform === 'win32') {
    for (const cand of ['py', 'py.exe']) {
      const r = spawnSync(cand, ['-3', '-c', 'import sys'], { windowsHide: true })
      if (r.status === 0) return [cand, '-3']
    }
  }
  return null
}

function fail(msg) {
  process.stderr.write(`[knowlp-mcp] ${msg}\n`)
  process.exit(1)
}

// P0-2: testing only `import mcp` lets through broken environments where the
// package is present but unusable (outdated/half-installed/mcp polluted by
// PYTHONPATH all import fine). Test the symbol actually used, FastMCP.
// The probe also strips PYTHONPATH (P0-3) so the probe environment matches the
// runtime one — otherwise a bad package on PYTHONPATH makes the probe pass
// falsely, and it crashes after the bootstrap is skipped.
// py is a [cmd, ...preArgs] array.
function hasMcp(py) {
  const env = { ...process.env }
  delete env.PYTHONPATH
  const r = spawnSync(py[0], [...py.slice(1), '-c', 'from mcp.server.fastmcp import FastMCP'],
                      { windowsHide: true, stdio: 'ignore', env })
  return r.status === 0
}

function ensureVenv(basePy) {
  if (existsSync(venvPython()) && hasMcp([venvPython()])) return venvPython()

  mkdirSync(dirname(VENV), { recursive: true })
  process.stderr.write('[knowlp-mcp] \u9996\u6b21\u542f\u52a8: \u81ea\u4e3e Python \u73af\u5883 (~/.knowlp-dsh/venv, \u7ea6 30s)\n')
  let r = spawnSync(basePy[0], [...basePy.slice(1), '-m', 'venv', VENV],
                    { windowsHide: true, stdio: 'inherit' })
  if (r.status !== 0) fail(`python -m venv \u5931\u8d25 (exit ${r.status})`)
  // pin mcp 1.x (aligned with mcp>=1.2,<2 in pyproject.toml): knowlp_mcp.py is
  // written against the 1.x API (mcp.server.fastmcp.FastMCP); after the mcp 2.0
  // rewrite that path no longer exists, so the hasMcp probe fails forever →
  // every launch reinstalls in a loop. Without the pin it installs 2.0 and crashes.
  r = spawnSync(venvPython(), ['-m', 'pip', 'install', '--quiet', 'mcp>=1.2,<2', 'pyyaml'],
                { windowsHide: true, stdio: 'inherit' })
  if (r.status !== 0) fail(`pip install mcp pyyaml \u5931\u8d25 (exit ${r.status}) — \u68c0\u67e5 pip \u7f51\u7edc/\u4ee3\u7406`)
  return venvPython()
}

function main() {
  const basePy = findPython()
  if (!basePy) fail('\u672a\u627e\u5230 Python 3 — \u8bf7\u5b89\u88c5 Python 3.11+ \u6216\u8bbe\u7f6e KNOWLP_PYTHON')

  let py = basePy
  if (!process.env.KNOWLP_PYTHON && !hasMcp(basePy)) {
    py = [ensureVenv(basePy)]
  }

  const serverPy = join(PKG_DIR, 'knowlp_mcp.py')
  if (!existsSync(serverPy)) fail(`\u5305\u5185\u7f3a\u5c11 knowlp_mcp.py: ${serverPy}`)

  // P0-3: strip PYTHONPATH before spawn — the PYTHONPATH forwarded by the host
  // session (Hermes/dsh/IDE) may point at another broken venv and hijack imports
  // (mcp installed in the wrong place / a bad package loaded).
  // The bootstrapped environment must resolve dependencies through its own venv.
  const childEnv = { ...process.env }
  delete childEnv.PYTHONPATH

  const child = spawn(py[0], [...py.slice(1), serverPy, ...process.argv.slice(2)], {
    cwd: PKG_DIR,
    stdio: 'inherit',
    env: childEnv,
    windowsHide: true,
  })
  child.on('error', (e) => fail(`spawn ${py[0]} \u5931\u8d25: ${e.message}`))
  child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)))
}

main()
