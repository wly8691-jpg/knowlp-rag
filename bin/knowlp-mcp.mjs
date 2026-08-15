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

// 返回 [cmd, ...preArgs] — 支持 `py -3` 这类带参数的启动形式
function findPython() {
  if (process.env.KNOWLP_PYTHON) return [process.env.KNOWLP_PYTHON]

  // 1. PATH 里的 python/python3 (正常环境)
  for (const cand of ['python', 'python3']) {
    const r = spawnSync(cand, ['-c', 'import sys'], { windowsHide: true })
    if (r.status === 0) return [cand]
  }

  // 2. 已自举过的 venv — 确定性绝对路径, 不依赖 PATH (P0-4: 宿主会话
  //    的 PATH 里没有 Python 目录时, 这是唯一稳定的解释器)
  if (existsSync(venvPython()) && hasMcp([venvPython()])) return [venvPython()]

  // 3. Windows: py launcher 不依赖 PATH (py.exe 在 C:\Windows 或注册表级)
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

// P0-2: 只测 `import mcp` 会放过"包在但不可用"的坏环境 (旧版/半装/被
// PYTHONPATH 污染的 mcp 都能 import 成功)。测真正用到的符号 FastMCP。
// 探测时同样剥离 PYTHONPATH (P0-3), 保证探测环境与运行环境一致 —
// 否则 PYTHONPATH 里的坏包让探测假阳性通过, 跳过自举后再崩。
// py 为 [cmd, ...preArgs] 数组。
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
  process.stderr.write('[knowlp-mcp] 首次启动: 自举 Python 环境 (~/.knowlp-dsh/venv, 约 30s)\n')
  let r = spawnSync(basePy[0], [...basePy.slice(1), '-m', 'venv', VENV],
                    { windowsHide: true, stdio: 'inherit' })
  if (r.status !== 0) fail(`python -m venv 失败 (exit ${r.status})`)
  // 锁 mcp 1.x (与 pyproject.toml 的 mcp>=1.2,<2 对齐): knowlp_mcp.py 按
  // 1.x API 编写 (mcp.server.fastmcp.FastMCP); mcp 2.0 重构后该路径不存在,
  // hasMcp 探测会永久失败 → 每次启动都重装循环。不锁会装到 2.0 并崩。
  r = spawnSync(venvPython(), ['-m', 'pip', 'install', '--quiet', 'mcp>=1.2,<2', 'pyyaml'],
                { windowsHide: true, stdio: 'inherit' })
  if (r.status !== 0) fail(`pip install mcp pyyaml 失败 (exit ${r.status}) — 检查 pip 网络/代理`)
  return venvPython()
}

function main() {
  const basePy = findPython()
  if (!basePy) fail('未找到 Python 3 — 请安装 Python 3.11+ 或设置 KNOWLP_PYTHON')

  let py = basePy
  if (!process.env.KNOWLP_PYTHON && !hasMcp(basePy)) {
    py = [ensureVenv(basePy)]
  }

  const serverPy = join(PKG_DIR, 'knowlp_mcp.py')
  if (!existsSync(serverPy)) fail(`包内缺少 knowlp_mcp.py: ${serverPy}`)

  // P0-3: spawn 前剥离 PYTHONPATH — 宿主会话 (Hermes/dsh/IDE) 透传的
  // PYTHONPATH 可能指向别的坏 venv, 会劫持 import (mcp 装错位/加载坏包)。
  // 自举环境必须靠自己的 venv 解析依赖。
  const childEnv = { ...process.env }
  delete childEnv.PYTHONPATH

  const child = spawn(py[0], [...py.slice(1), serverPy, ...process.argv.slice(2)], {
    cwd: PKG_DIR,
    stdio: 'inherit',
    env: childEnv,
    windowsHide: true,
  })
  child.on('error', (e) => fail(`spawn ${py[0]} 失败: ${e.message}`))
  child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)))
}

main()
