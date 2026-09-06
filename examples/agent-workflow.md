# Agent Workflow — when to call KnowLP, and what never to do

KnowLP is a memory retrieval layer over a Markdown vault. The Agent's job is to
use it as evidence, not to treat it as an oracle.

## When to call

- **Historical decisions**: "why did we choose X", "what did we decide about Y"
- **Project background**: notes that predate the current conversation
- **Constraints and limits**: known limitations recorded in past work
- **Prerequisite knowledge**: before reading a hard note, ask for its
  prerequisites (P-Agent results)
- **Alternative approaches**: when the current approach stalls, ask for
  similar/comparable notes (S-Agent / Vector results)
- **Visual memory** (PixelRAG, if configured): "I saw a diagram about this"
- **After retrieval**: read the actual note (`knowlp_get_note`) before citing
  anything from it

## How to interpret results

| source tag | meaning | usage |
|---|---|---|
| `Direct match` | title/name hit | usually the note the user means |
| `P-Agent (prerequisite)` | read this FIRST to understand the hit | read before the hit |
| `S-Agent (similarity)` | comparable/related view | use as contrast, not as the answer |
| `Vector (semantic)` | fuzzy semantic match | verify by reading; may be tangential |
| `Graph expansion (spreading)` | reached via graph edges from an anchor | check the path reason |

## Forbidden

1. Do not present an empty result as a find. Say "nothing in the vault".
2. Do not treat a similar note (S-Agent/Vector) as the prerequisite fact
   (P-Agent). The tags mean different things.
3. Do not write to the vault without explicit user confirmation.
4. Do not submit feedback (`knowlp_record_correction`) without the user's
   explicit judgment of which result was better.
5. Do not present remote visual results (PixelRAG) as local notes.
6. Do not declare KnowLP "broken" because one engine is unavailable — check
   `knowlp_stats` and report which engines answered.
