// knowlp-dsh — native DeepSeek Harness plugin for KnowLP dual knowledge-graph retrieval
//
// Three things (that the MCP adapter cannot do):
//   1. Tools: knowlp_search / knowlp_get_note / knowlp_stats /
//            knowlp_record_feedback / skill_search (optional)
//   2. Recall on prompt: the first user message of each turn triggers one retrieval;
//      the top-N results are injected into the model context via agent.inject() as a snapshot
//   3. Automatic feedback at turn end: on turn/end, detect which of the retrieved
//      note titles the assistant output cited, map them back to real dual_graph
//      edges and write them into the weight loop
//      (only the explicit path writes feedback_log.jsonl — same iron rule as MCP)
//
// Depends on the Python-side knowlp package: pip install -e ".[mcp]"
// Environment variables:
//   KNOWLP_PYTHON        override the python command (defaults to python on PATH)
//   KNOWLP_SKILL_INDEX   when set, additionally registers the skill_search tool
//   KNOWLP_AUTO_INJECT   set to '0' to disable automatic context injection
//   KNOWLP_AUTO_FEEDBACK set to '0' to disable automatic feedback

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

// ── Python subprocess ─────────────────────────────────────────

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

// Retrieval goes through the knowlp_search.py CLI --json output (includes matched_nodes, merged)
// —— matched_nodes is the basis the automatic feedback uses to map notes back to real graph edges
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

// vault is resolved once at startup (used by get_note)
let vault = ''

// ── Tools ─────────────────────────────────────────────────────

function fmtSearchHit(hit, i) {
  const title = hit.title || ''
  const path = hit.path || ''
  const score = typeof hit.score === 'number' ? hit.score.toFixed(2) : ''
  return `${i + 1}. \u300a${title}\u300b ${path}${score ? ` (${score})` : ''}`
}

async function executeSearch(args) {
  const r = await search(String(args.query), Math.max(1, Math.min(20, Number(args.limit) || 5)))
  if (!r.ok) return { ok: false, error: r.error }
  return { ok: true, hits: r.hits }
}

function renderSearch(_args, value) {
  if (!value || value.ok !== true) return [{ type: 'text', text: `knowlp_search \u5931\u8d25: ${value?.error || 'unknown'}` }]
  if (!value.hits.length) return [{ type: 'text', text: '\u672a\u68c0\u7d22\u5230\u76f8\u5173\u7b14\u8bb0\u3002' }]
  const lines = [`KnowLP \u68c0\u7d22\u5230 ${value.hits.length} \u6761:`, ...value.hits.map(fmtSearchHit)]
  return [{ type: 'text', text: lines.join('\n') }]
}

function safeNotePath(p) {
  const root = vault
  if (!root) return null
  const abs = resolve(root, p)
  const rootNorm = resolve(root) + sep
  if (abs !== resolve(root) && !abs.startsWith(rootNorm)) return null // guard against path traversal
  return abs
}

function executeGetNote(args) {
  const abs = safeNotePath(String(args.path))
  if (!abs) return { ok: false, error: 'KNOWLP_VAULT \u672a\u914d\u7f6e\u6216\u8def\u5f84\u8d8a\u754c' }
  let text
  try {
    text = readFileSync(abs, 'utf-8').slice(0, Math.max(100, Math.min(30000, Number(args.max_chars) || 8000)))
  } catch (e) {
    return { ok: false, error: `\u8bfb\u53d6\u5931\u8d25: ${e.message}` }
  }
  return { ok: true, text }
}

function renderGetNote(_args, value) {
  if (!value || value.ok !== true) return [{ type: 'text', text: `knowlp_get_note \u5931\u8d25: ${value?.error}` }]
  return [{ type: 'text', text: value.text }]
}

function renderStats(_args, value) {
  if (!value) return [{ type: 'text', text: 'knowlp_stats \u5931\u8d25' }]
  return [{ type: 'text', text: JSON.stringify(value, null, 2) }]
}

function renderSkillSearch(_args, value) {
  if (!value || value.available === false) return [{ type: 'text', text: `skill_search \u4e0d\u53ef\u7528: ${value?.reason || 'unknown'}` }]
  const hits = value.hits || []
  if (!hits.length) return [{ type: 'text', text: '\u672a\u68c0\u7d22\u5230\u76f8\u5173\u6280\u80fd\u3002' }]
  return [{ type: 'text', text: hits.map((h, i) => `${i + 1}. ${h.name || h.title || '?'}: ${h.description || h.desc || ''}`).join('\n') }]
}

function renderFeedback(_args, value) {
  if (!value) return [{ type: 'text', text: 'knowlp_record_feedback \u5931\u8d25' }]
  if (value.error) return [{ type: 'text', text: `\u53cd\u9988\u5199\u5165\u5931\u8d25: ${value.error}` }]
  return [{ type: 'text', text: `\u53cd\u9988\u5df2\u8bb0\u5f55: consumed=${value.consumed_count ?? 0}, ignored=${value.ignored_count ?? 0}` }]
}

// ── Automatic injection + automatic feedback ─────────────────

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
  const lines = ['[KnowLP \u81ea\u52a8\u68c0\u7d22] \u7b14\u8bb0\u5e93\u4e2d\u4e0e\u672c\u8f6e\u95ee\u9898\u76f8\u5173\u7684\u7b14\u8bb0\uff08\u5982\u9700\u539f\u6587\u53ef\u8c03\u7528 knowlp_get_note\uff09:']
  items.forEach((hit, i) => lines.push(fmtSearchHit(hit, i)))
  return lines.join('\n')
}

async function onUserMessage(session, event) {
  const rec = sess(session.id)
  if (!rec.agent) return
  if (rec.injectedTurn === rec.lastTurn) return // inject only once per turn
  if (event.source?.kind === 'plugin') return // do not respond to the injected content itself
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
      sections: [{ name: 'KnowLP \u7b14\u8bb0\u68c0\u7d22', text: snapshot }],
    },
  })
  console.log(`[knowlp-dsh] injected ${r.hits.length} notes for turn ${rec.lastTurn}`)
}

function onTurnEnd(session, event) {
  const rec = sess(session.id)

  // Collect this turn's assistant text (scan back from the log tail to turn/start)
  let assistantText = ''
  for (let i = session.events.length - 1; i >= 0; i--) {
    const e = session.events[i]
    if (e.type === 'turn/start' && e.turn === event.turn) break
    if (e.type === 'assistant/message') assistantText += '\n' + msgText(e.message)
  }

  // Automatic ingest (layer 1: hook-triggered incremental graph build, independent of AUTO_FEEDBACK / injection / retrieval hits)
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

  // Automatic feedback (weight loop): still gated by AUTO_FEEDBACK + injection + retrieval-hit guards
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
  if (consumed.length === 0) return // no note cited → do not write feedback (avoid noise)

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

// ── Plugin entry ──────────────────────────────────────────────

/** @param {import('@deepseek-ai/cordis').Context} ctx */
export function apply(ctx) {
  // Resolve vault at startup (used by get_note)
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
    description: '\u5728\u4f60\u7684 Markdown \u7b14\u8bb0\u5e93(Obsidian vault)\u4e2d\u505a\u53cc\u77e5\u8bc6\u56fe\u8c31\u68c0\u7d22: \u524d\u7f6e\u4f9d\u8d56\u94fe(P-Agent)\u3001\u76f8\u4f3c\u7b14\u8bb0(S-Agent)\u3001\u6bb5\u843d\u5339\u914d\u4e0e\u6df7\u5408\u5411\u91cf\u3002\u8fd4\u56de\u5e26\u9605\u8bfb\u8def\u5f84\u7684\u6392\u5e8f\u7ed3\u679c\u3002',
    parameters: {
      query: { type: 'string', required: true, description: '\u68c0\u7d22\u67e5\u8be2(\u4e2d\u6587/\u82f1\u6587\u5747\u53ef)' },
      limit: { type: 'number', required: false, description: '\u6700\u591a\u8fd4\u56de\u6761\u6570, \u9ed8\u8ba4 5, \u6700\u5927 20' },
    },
    output: { schema: { type: 'object' }, render: renderSearch },
    execute: executeSearch,
  })

  ctx.tools.register({
    name: 'knowlp_get_note',
    description: '\u8bfb\u53d6\u7b14\u8bb0\u539f\u6587(\u53ea\u8bfb)\u3002path \u5fc5\u987b\u662f\u68c0\u7d22\u7ed3\u679c\u91cc\u7ed9\u51fa\u7684 vault \u76f8\u5bf9\u8def\u5f84, \u9632\u8def\u5f84\u7a7f\u8d8a\u3002',
    parameters: {
      path: { type: 'string', required: true, description: 'vault \u76f8\u5bf9\u8def\u5f84, \u5982 Notes/\u793a\u4f8b\u7b14\u8bb0.md' },
      max_chars: { type: 'number', required: false, description: '\u6700\u5927\u8fd4\u56de\u5b57\u7b26\u6570, \u9ed8\u8ba4 8000' },
    },
    output: { schema: { type: 'object' }, render: renderGetNote },
    execute: executeGetNote,
  })

  ctx.tools.register({
    name: 'knowlp_stats',
    description: 'KnowLP \u7d22\u5f15\u7edf\u8ba1: \u8282\u70b9\u6570\u3001\u8fb9\u6570\u3001\u53cd\u9988\u65e5\u5fd7\u884c\u6570\u7b49\u3002',
    parameters: {},
    output: { schema: { type: 'object' }, render: renderStats },
    execute: () => runJson(['-c', STATS_CODE]).then((r) => (r.ok ? r.value : null)),
  })

  ctx.tools.register({
    name: 'knowlp_record_feedback',
    description: '\u663e\u5f0f\u8bb0\u5f55\u68c0\u7d22\u53cd\u9988\u4ee5\u8c03\u4f18\u56fe\u8fb9\u6743\u91cd(\u6743\u91cd\u95ed\u73af\u7684\u552f\u4e00\u5199\u5165\u53e3, \u68c0\u7d22\u672c\u8eab\u6c38\u4e0d\u5199\u53cd\u9988)\u3002consumed/ignored \u4e3a\u8fb9\u5b57\u7b26\u4e32 "from||to||type", type \u53d6 pre \u6216 sim\u3002',
    parameters: {
      session_id: { type: 'string', required: true, description: '\u4f1a\u8bdd\u552f\u4e00\u6807\u8bc6' },
      query: { type: 'string', required: true, description: '\u539f\u59cb\u67e5\u8be2\u6587\u672c' },
      consumed: { type: 'array', required: false, description: '\u5b9e\u9645\u4f7f\u7528\u4e86\u7684\u8fb9, \u5982 ["A||B||pre"]' },
      ignored: { type: 'array', required: false, description: '\u68c0\u7d22\u5230\u4f46\u672a\u4f7f\u7528\u7684\u8fb9' },
      satisfied: { type: 'boolean', required: false, description: '\u68c0\u7d22\u662f\u5426\u6ee1\u610f, \u9ed8\u8ba4 true' },
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
      description: '\u5728\u6280\u80fd\u56fe\u8c31\u7d22\u5f15\u4e2d\u641c\u7d22\u6280\u80fd(BM25)\u3002\u4ec5\u5f53 KNOWLP_SKILL_INDEX \u914d\u7f6e\u65f6\u53ef\u7528\u3002',
      parameters: {
        query: { type: 'string', required: true, description: '\u6280\u80fd\u68c0\u7d22\u67e5\u8be2' },
        top_k: { type: 'number', required: false, description: '\u8fd4\u56de\u6761\u6570, \u9ed8\u8ba4 8' },
      },
      output: { schema: { type: 'object' }, render: renderSkillSearch },
      execute: (args) => runJson(['-c', SKILL_CODE, String(args.query), String(args.top_k || 8)]).then((r) => (r.ok ? r.value : null)),
    })
  }

  console.log('[knowlp-dsh] plugin loaded')
}
