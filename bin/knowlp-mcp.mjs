#!/usr/bin/env node
// knowlp-mcp launcher — dsh bundle 的 MCP stdio 入口
//
// 职责: 找到 (或自举) 一个能跑 knowlp_mcp.py 的 Python 环境, 然后把
// stdio 原样交给 Python 侧的 MCP 服务器。用户无需手动 pip install。
//
// 行为:
//   1. KNOWLP_PYTHON 已设置 → 直接用它 (假设 mcp SDK 已装)
//   2. 否则用 ~/.knowlp-dsh/venv (不存在则 python -m venv 创建,
//      并 pip install mcp pyyaml — 仅首次, 之后秒起)
//   3. 用该 Python 运行本包内置的 knowlp_mcp.py, cwd = 包目录
//
// 环境变量透传: KNOWLP_VAULT / KNOWLP_GRAPH_DIR / KNOWLP_SKILL_INDEX 等
// 全部原样传给 Python 子进程。

import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const PKG_DIR = dirname(dirname(fileURLToPath(import.meta.url))) // npm 包根
const VENV = process.env.KNOWLP_VENV || join(homedir(), '.knowlp-dsh', 'venv')

function venvPython() {
  return process.platform === 'win32'
    ? join(VENV, 'Scripts', 'python.exe')
    : join(VENV, 'bin', 'python')
}

function findPython() {
  if (process.env.KNOWLP_PYTHON) return process.env.KNOWLP_PYTHON
  for (const cand of ['python', 'python3']) {
    const r = spawnSync(cand, ['-c', 'import sys'], { windowsHide: true })
    if (r.status === 0) return cand
  }
  return null
}

function fail(msg) {
  process.stderr.write(`[knowlp-mcp] ${msg}\n`)
  process.exit(1)
}

function hasMcp(py) {
  const r = spawnSync(py, ['-c', 'import mcp'], { windowsHide: true, stdio: 'ignore' })
  return r.status === 0
}

function ensureVenv(basePy) {
  if (existsSync(venvPython()) && hasMcp(venvPython())) return venvPython()

  mkdirSync(dirname(VENV), { recursive: true })
  process.stderr.write('[knowlp-mcp] 首次启动: 自举 Python 环境 (~/.knowlp-dsh/venv, 约 30s)\n')
  let r = spawnSync(basePy, ['-m', 'venv', VENV], { windowsHide: true, stdio: 'inherit' })
  if (r.status !== 0) fail(`python -m venv 失败 (exit ${r.status})`)
  r = spawnSync(venvPython(), ['-m', 'pip', 'install', '--quiet', 'mcp', 'pyyaml'],
                { windowsHide: true, stdio: 'inherit' })
  if (r.status !== 0) fail(`pip install mcp pyyaml 失败 (exit ${r.status}) — 检查 pip 网络/代理`)
  return venvPython()
}

function main() {
  const basePy = findPython()
  if (!basePy) fail('未找到 Python 3 — 请安装 Python 3.11+ 或设置 KNOWLP_PYTHON')

  let py = basePy
  if (!process.env.KNOWLP_PYTHON && !hasMcp(basePy)) {
    py = ensureVenv(basePy)
  }

  const serverPy = join(PKG_DIR, 'knowlp_mcp.py')
  if (!existsSync(serverPy)) fail(`包内缺少 knowlp_mcp.py: ${serverPy}`)

  const child = spawn(py, [serverPy, ...process.argv.slice(2)], {
    cwd: PKG_DIR,
    stdio: 'inherit',
    env: process.env,
    windowsHide: true,
  })
  child.on('error', (e) => fail(`spawn ${py} 失败: ${e.message}`))
  child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)))
}

main()
