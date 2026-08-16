// knowlp-dsh — KnowLP 双知识图谱检索的 DeepSeek Harness 原生插件
//
// 三件事（MCP 适配器做不到的）：
//   1. 工具: knowlp_search / knowlp_get_note / knowlp_stats /
//            knowlp_record_feedback / skill_search(可选)
//   2. 提示时召回: 每个 turn 的第一条 user 消息触发一次检索，
//      top-N 结果以 snapshot 形式 agent.inject() 注入模型上下文
//   3. 回合结束自动反馈: turn/end 时检测 assistant 输出引用了哪些
//      检索到的笔记标题，映射回 dual_graph 真实边并写入权重闭环
//      （只有显式路径写 feedback_log.jsonl —— 与 MCP 同一铁律）
//
// 依赖 Python 侧的 knowlp 包: pip install -e ".[mcp]"
// 环境变量:
//   KNOWLP_PYTHON        覆盖 python 命令（默认 PATH 上的 python）
//   KNOWLP_SKILL_INDEX   设置后额外注册 skill_search 工具
//   KNOWLP_AUTO_INJECT   设 '0' 关闭自动上下文注入
//   KNOWLP_AUTO_FEEDBACK 设 '0' 关闭自动反馈

import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve, sep } from 'node:path'

export const name = 'knowlp-dsh'
export const inject = ['tools']

const PYTHON = process.env.KNOWLP_PYTHON || 'python'
const AUTO_INJECT = process.env.KNOWLP_AUTO_INJECT !== '0'
const AUTO_FEEDBACK = process.env.KNOWLP_AUTO_FEEDBACK !== '0'
const AUTO_INGEST = process.env.KNOWLP_AUTO_INGEST !== '0'
const CONTEXT_LIMIT = 3
const MIN_QUERY_CHARS = 3
const MIN_INGEST_CHARS = 20
const TIMEOUT_MS = 60_000

// ── Python 子进程 ─────────────────────────────────────────────

function runJson(args, { stdin = null } = {}) {
  return new Promise((resolvePromise) => {
    const child = spawn(PYTHON, args, { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
    let out = ''
    let err = ''
    const timer = setTimeout(() => { child.kill(); finish(null, `timeout ${TIMEOUT_MS}ms`) }, TIMEOUT_MS)
    let done = false
    const finish = (value, error) => {
      if (done) return
      done = true
      clearTimeout(timer)
      resolvePromise({ ok: error === undefined && value !== null, value, error })
    }
    child.stdout.on('data', (d) => { out += d })
    child.stderr.on('data', (d) => { err += d })
    child.on('error', (e) => finish(null, e.message))
    child.on('close', () => {
      if (err.trim()) console.error(`[knowlp-dsh] python stderr: ${err.trim().slice(0, 500)}`)
      try { finish(JSON.parse(out), undefined) }
      catch { finish(null, `non-JSON output: ${out.slice(0, 200)}`) }
    })
    if (stdin != null) child.stdin.end(stdin)
    else child.stdin.end()
  })
}

// 检索走 knowlp_search.py CLI 的 --json 输出（含 matched_nodes, merged）
// —— matched_nodes 是自动反馈把笔记映射回真实图边时的依据
async function search(query, limit) {
  const r = await runJson(['-m', 'knowlp_search', query, '--json', '--limit', String(limit)])
  if (!r.ok) return r
  const merged = (r.value?.merged || []).map((m) => ({
    title: m.name || '',
    path: m.path || '',
    sub_source: m.source || '',
    score: (m.match_score ?? (m.rank_score ?? 0) * 100) / 100,
  }))
  return { ok: true, hits: merged, matched: r.value?.matched_nodes || [], raw: r.value }
}

const STATS_CODE = [
  'import json',
  'from knowlp_mcp import _graph_stats',
  "print(json.dumps(_graph_stats(), ensure_ascii=False))",
].join('; ')

const SKILL_CODE = [
  'import json,sys',
  'from knowlp_mcp import skill_search',
  "print(json.dumps(skill_search(sys.argv[1], int(sys.argv[2])), ensure_ascii=False))",
].join('; ')

const FEEDBACK_CODE = [
  'import json,sys',
  'from record_feedback import parse_edge, record',
  'd=json.load(sys.stdin)',
  'edges=[]',
  'for s in (d.get("consumed") or []):',
  '    try: edges.append(parse_edge(s))',
  '    except Exception: pass',
  'ign=[]',
  'for s in (d.get("ignored") or []):',
  '    try: ign.append(parse_edge(s))',
  '    except Exception: pass',
  'r=record(d.get("session_id"), d.get("query",""), edges, ign, d.get("satisfied",True), d.get("confidence","medium"))',
  "print(json.dumps(r, ensure_ascii=False))",
].join('\n')

const VAULT_CODE = ['import json', 'from config import VAULT', 'print(json.dumps(str(VAULT or "")))'].join('; ')

// vault 在启动时解析一次（get_note 用）
let vault = ''

// ── 工具 ──────────────────────────────────────────────────────

function fmtSearchHit(hit, i) {
  const title = hit.title || ''
  const path = hit.path || ''
  const score = typeof hit.score === 'number' ? hit.score.toFixed(2) : ''
  return `${i + 1}. 《${title}》 ${path}${score ? ` (${score})` : ''}`
}

async function executeSearch(args) {
  const r = await search(String(args.query), Math.max(1, Math.min(20, Number(args.limit) || 5)))
  if (!r.ok) return { ok: false, error: r.error }
  return { ok: true, hits: r.hits }
}

function renderSearch(_args, value) {
  if (!value || value.ok !== true) return [{ type: 'text', text: `knowlp_search 失败: ${value?.error || 'unknown'}` }]
  if (!value.hits.length) return [{ type: 'text', text: '未检索到相关笔记。' }]
  const lines = [`KnowLP 检索到 ${value.hits.length} 条:`, ...value.hits.map(fmtSearchHit)]
  return [{ type: 'text', text: lines.join('\n') }]
}

function safeNotePath(p) {
  const root = vault
  if (!root) return null
  const abs = resolve(root, p)
  const rootNorm = resolve(root) + sep
  if (abs !== resolve(root) && !abs.startsWith(rootNorm)) return null // 防路径穿越
  return abs
}

function executeGetNote(args) {
  const abs = safeNotePath(String(args.path))
  if (!abs) return { ok: false, error: 'KNOWLP_VAULT 未配置或路径越界' }
  let text
  try {
    text = readFileSync(abs, 'utf-8').slice(0, Math.max(100, Math.min(30000, Number(args.max_chars) || 8000)))
  } catch (e) {
    return { ok: false, error: `读取失败: ${e.message}` }
  }
  return { ok: true, text }
}

function renderGetNote(_args, value) {
  if (!value || value.ok !== true) return [{ type: 'text', text: `knowlp_get_note 失败: ${value?.error}` }]
  return [{ type: 'text', text: value.text }]
}

function renderStats(_args, value) {
  if (!value) return [{ type: 'text', text: 'knowlp_stats 失败' }]
  return [{ type: 'text', text: JSON.stringify(value, null, 2) }]
}

function renderSkillSearch(_args, value) {
  if (!value || value.available === false) return [{ type: 'text', text: `skill_search 不可用: ${value?.reason || 'unknown'}` }]
  const hits = value.hits || []
  if (!hits.length) return [{ type: 'text', text: '未检索到相关技能。' }]
  return [{ type: 'text', text: hits.map((h, i) => `${i + 1}. ${h.name || h.title || '?'}: ${h.description || h.desc || ''}`).join('\n') }]
}

function renderFeedback(_args, value) {
  if (!value) return [{ type: 'text', text: 'knowlp_record_feedback 失败' }]
  if (value.error) return [{ type: 'text', text: `反馈写入失败: ${value.error}` }]
  return [{ type: 'text', text: `反馈已记录: consumed=${value.consumed_count ?? 0}, ignored=${value.ignored_count ?? 0}` }]
}

// ── 自动注入 + 自动反馈 ───────────────────────────────────────

/** @type {Map<string, {agent: any, lastTurn: number, injectedTurn: number, lastQuery: string, retrieved: any[], matched: any[]}>} */
const sessions = new Map()

function sess(sessionId) {
  if (!sessions.has(sessionId)) {
    sessions.set(sessionId, { agent: null, lastTurn: -1, injectedTurn: -1, lastQuery: '', retrieved: [], matched: [] })
  }
  return sessions.get(sessionId)
}

function msgText(msg) {
  return (msg?.content || [])
    .filter((b) => b && b.type === 'text')
    .map((b) => b.text)
    .join('\n')
    .trim()
}

function buildSnapshot(items) {
  const lines = ['[KnowLP 自动检索] 笔记库中与本轮问题相关的笔记（如需原文可调用 knowlp_get_note）:']
  items.forEach((hit, i) => lines.push(fmtSearchHit(hit, i)))
  return lines.join('\n')
}

async function onUserMessage(session, event) {
  const rec = sess(session.id)
  if (!rec.agent) return
  if (rec.injectedTurn === rec.lastTurn) return // 每个 turn 只注入一次
  if (event.source?.kind === 'plugin') return // 不响应注入内容自身
  const text = msgText(event)
  if (text.length < MIN_QUERY_CHARS) return

  const r = await search(text, CONTEXT_LIMIT)
  if (!r.ok || !Array.isArray(r.hits) || r.hits.length === 0) return

  rec.injectedTurn = rec.lastTurn
  rec.lastQuery = text
  rec.retrieved = r.hits
  rec.matched = r.matched
  const snapshot = buildSnapshot(r.hits)
  rec.agent.inject({
    id: randomUUID(),
    role: 'user',
    content: [{ type: 'text', text: snapshot }],
    source: {
      kind: 'plugin',
      plugin: name,
      form: 'snapshot',
      sections: [{ name: 'KnowLP 笔记检索', text: snapshot }],
    },
  })
  console.log(`[knowlp-dsh] injected ${r.hits.length} notes for turn ${rec.lastTurn}`)
}

function onTurnEnd(session, event) {
  const rec = sess(session.id)

  // 收集本 turn 的 assistant 文本（从日志尾部回扫到 turn/start）
  let assistantText = ''
  for (let i = session.events.length - 1; i >= 0; i--) {
    const e = session.events[i]
    if (e.type === 'turn/start' && e.turn === event.turn) break
    if (e.type === 'assistant/message') assistantText += '\n' + msgText(e.message)
  }

  // 自动入库（层 1：钩子触发增量建图，独立于 AUTO_FEEDBACK / 注入 / 检索命中）
  if (AUTO_INGEST && assistantText.trim().length >= MIN_INGEST_CHARS) {
    runJson(['-m', 'increment'], { stdin: assistantText }).then((r) => {
      if (r.ok && r.value?.judged) {
        console.log(`[knowlp-dsh] ingested decree: ${r.value.saved} (+${r.value.edges_added} edges)`)
      } else if (r.ok) {
        console.log(`[knowlp-dsh] ingest skipped: ${r.value?.reason}`)
      } else {
        console.error(`[knowlp-dsh] ingest failed: ${r.error}`)
      }
    })
  }

  // 自动反馈（权重闭环）：仍需 AUTO_FEEDBACK + 注入 + 检索命中守卫
  if (!AUTO_FEEDBACK) return
  if (rec.injectedTurn !== event.turn) return
  if (!rec.lastQuery || !rec.retrieved.length) return

  const consumed = []
  const ignored = []
  for (const hit of rec.retrieved) {
    const title = hit.title || ''
    if (!title) continue
    const cited = assistantText.includes(title) || assistantText.includes(`${title}.md`)
    if (cited) consumed.push({ title, sub_source: hit.sub_source || '' })
    else ignored.push({ title, sub_source: hit.sub_source || '' })
  }
  if (consumed.length === 0) return // 没引用任何笔记 → 不写反馈（避免噪声）

  const matched = rec.matched.map((m) => (typeof m === 'string' ? m : m.name)).filter(Boolean)
  const payload = JSON.stringify({
    session_id: session.id,
    query: rec.lastQuery,
    matched,
    consumed,
    ignored,
  })
  runJson(['-m', 'auto_feedback'], { stdin: payload }).then((r) => {
    if (r.ok) console.log(`[knowlp-dsh] auto feedback: ${JSON.stringify(r.value)}`)
    else console.error(`[knowlp-dsh] auto feedback failed: ${r.error}`)
  })
}

// ── 插件入口 ──────────────────────────────────────────────────

/** @param {import('@deepseek-ai/cordis').Context} ctx */
export function apply(ctx) {
  // 启动时解析 vault（get_note 用）
  runJson(['-c', VAULT_CODE]).then((r) => {
    if (r.ok && typeof r.value === 'string') {
      vault = r.value
      console.log(`[knowlp-dsh] vault: ${vault}`)
    }
  })

  ctx.on('agent/created', ({ agent }) => {
    const rec = sess(agent.id)
    rec.agent = agent
    console.log(`[knowlp-dsh] attached to session ${agent.id}`)
  })

  ctx.on('session/event', (session, event) => {
    if (event.type === 'turn/start') sess(session.id).lastTurn = event.turn
    if (event.type === 'user/message' && AUTO_INJECT) onUserMessage(session, event)
    if (event.type === 'turn/end') onTurnEnd(session, event)
  })

  ctx.tools.register({
    name: 'knowlp_search',
    description: '在你的 Markdown 笔记库(Obsidian vault)中做双知识图谱检索: 前置依赖链(P-Agent)、相似笔记(S-Agent)、段落匹配与混合向量。返回带阅读路径的排序结果。',
    parameters: {
      query: { type: 'string', required: true, description: '检索查询(中文/英文均可)' },
      limit: { type: 'number', required: false, description: '最多返回条数, 默认 5, 最大 20' },
    },
    output: { schema: { type: 'object' }, render: renderSearch },
    execute: executeSearch,
  })

  ctx.tools.register({
    name: 'knowlp_get_note',
    description: '读取笔记原文(只读)。path 必须是检索结果里给出的 vault 相对路径, 防路径穿越。',
    parameters: {
      path: { type: 'string', required: true, description: 'vault 相对路径, 如 Notes/示例笔记.md' },
      max_chars: { type: 'number', required: false, description: '最大返回字符数, 默认 8000' },
    },
    output: { schema: { type: 'object' }, render: renderGetNote },
    execute: executeGetNote,
  })

  ctx.tools.register({
    name: 'knowlp_stats',
    description: 'KnowLP 索引统计: 节点数、边数、反馈日志行数等。',
    parameters: {},
    output: { schema: { type: 'object' }, render: renderStats },
    execute: () => runJson(['-c', STATS_CODE]).then((r) => (r.ok ? r.value : null)),
  })

  ctx.tools.register({
    name: 'knowlp_record_feedback',
    description: '显式记录检索反馈以调优图边权重(权重闭环的唯一写入口, 检索本身永不写反馈)。consumed/ignored 为边字符串 "from||to||type", type 取 pre 或 sim。',
    parameters: {
      session_id: { type: 'string', required: true, description: '会话唯一标识' },
      query: { type: 'string', required: true, description: '原始查询文本' },
      consumed: { type: 'array', required: false, description: '实际使用了的边, 如 ["A||B||pre"]' },
      ignored: { type: 'array', required: false, description: '检索到但未使用的边' },
      satisfied: { type: 'boolean', required: false, description: '检索是否满意, 默认 true' },
      confidence: { type: 'string', required: false, description: 'high | medium | low | none' },
    },
    output: { schema: { type: 'object' }, render: renderFeedback },
    execute: (args) => runJson(['-c', FEEDBACK_CODE], {
      stdin: JSON.stringify({
        session_id: args.session_id,
        query: args.query,
        consumed: args.consumed,
        ignored: args.ignored,
        satisfied: args.satisfied ?? true,
        confidence: args.confidence || 'medium',
      }),
    }).then((r) => (r.ok ? r.value : null)),
  })

  if (process.env.KNOWLP_SKILL_INDEX) {
    ctx.tools.register({
      name: 'skill_search',
      description: '在技能图谱索引中搜索技能(BM25)。仅当 KNOWLP_SKILL_INDEX 配置时可用。',
      parameters: {
        query: { type: 'string', required: true, description: '技能检索查询' },
        top_k: { type: 'number', required: false, description: '返回条数, 默认 8' },
      },
      output: { schema: { type: 'object' }, render: renderSkillSearch },
      execute: (args) => runJson(['-c', SKILL_CODE, String(args.query), String(args.top_k || 8)]).then((r) => (r.ok ? r.value : null)),
    })
  }

  console.log('[knowlp-dsh] plugin loaded')
}
