#!/usr/bin/env python
"""
KnowLP-RAG: Vector Index Layer
Two modes:
  --build          : Fast n-gram index (CPU-safe, ~1s)
  --build-real     : Real embedding index with Qwen3-VL-Embedding-2B (needs GPU)
"""
import json, sys, re
from pathlib import Path
from collections import Counter
import numpy as np

from config import VAULT, GRAPH_DIR, MODEL_PATH

def load_meta():
    return json.loads((GRAPH_DIR / 'meta_index.json').read_text(encoding='utf-8'))


# ============================================================
# FAST MODE: Character n-gram inverted index (CPU-safe)
# ============================================================

def build_ngram_index(meta_list: list[dict]) -> dict:
    """Build fast character n-gram inverted index. ~1 second for 254 docs."""
    print("   Building character n-gram index (Chinese-optimized)...")
    
    all_texts = []
    for m in meta_list:
        content = m.get('name', '') + ' ' + m.get('summary', '')
        tags = ' '.join(m.get('tags', []))
        headings = ' '.join(m.get('headings', []))
        all_texts.append(f"{content} {tags} {headings}")
    
    def get_ngrams(text, n=2):
        text = text.lower()
        return {text[i:i+n] for i in range(len(text) - n + 1)}
    
    inv_index = {}
    doc_ngrams = []
    for doc_id, text in enumerate(all_texts):
        ngrams = get_ngrams(text, 2) | get_ngrams(text, 3)
        doc_ngrams.append(ngrams)
        for ng in ngrams:
            inv_index.setdefault(ng, []).append(doc_id)
    
    def get_terms(text):
        text = re.sub(r'[^\u4e00-\u9fff\w]', ' ', text.lower())
        terms = set()
        for w in text.split():
            if len(w) >= 2:
                terms.add(w)
                for i in range(len(w)-1):
                    terms.add(w[i:i+2])
        return terms
    
    term_index = {}
    for doc_id, text in enumerate(all_texts):
        for t in get_terms(text):
            term_index.setdefault(t, []).append(doc_id)
    
    return {
        'type': 'character_ngram_inverted_index',
        'ngram_index': {k: list(v) for k, v in inv_index.items()},
        'term_index': {k: list(v) for k, v in term_index.items()},
        'total_docs': len(meta_list),
    }


def ngram_search(query: str, index: dict, meta_list: list[dict], top_k: int = 10) -> list[dict]:
    """Search using character n-gram overlap (BM25-like scoring)."""
    def get_ngrams(text, n=2):
        return {text.lower()[i:i+n] for i in range(len(text) - n + 1)}
    
    def get_terms(text):
        text = re.sub(r'[^\u4e00-\u9fff\w]', ' ', text.lower())
        terms = set()
        for w in text.split():
            if len(w) >= 2:
                terms.add(w)
                for i in range(len(w)-1):
                    terms.add(w[i:i+2])
        return terms
    
    query_ngrams = get_ngrams(query, 2) | get_ngrams(query, 3)
    query_terms = get_terms(query)
    
    doc_scores = Counter()
    total_docs = index['total_docs']
    ngram_index = index['ngram_index']
    term_index = index['term_index']
    
    for ng in query_ngrams:
        if ng in ngram_index:
            docs = ngram_index[ng]
            idf = np.log((total_docs - len(docs) + 0.5) / (len(docs) + 0.5) + 1)
            for doc_id in docs:
                doc_scores[doc_id] += idf
    
    for term in query_terms:
        if term in term_index:
            docs = term_index[term]
            idf = np.log((total_docs - len(docs) + 0.5) / (len(docs) + 0.5) + 1)
            for doc_id in docs:
                doc_scores[doc_id] += idf * 2
    
    ranked = sorted(doc_scores.items(), key=lambda x: -x[1])[:top_k]
    
    results = []
    for doc_id, score in ranked:
        if doc_id < len(meta_list):
            m = meta_list[doc_id]
            results.append({
                'name': m['name'],
                'path': m['path'],
                'score': round(score, 2),
                'type': 'ngram_semantic',
            })
    return results

# Alias for backward compatibility with knowlp_search.py
vector_search = ngram_search

# ============================================================
# REAL MODE: Qwen3-VL-Embedding-2B (requires GPU)
# ============================================================

_model = None
_tokenizer = None

def get_qwen_model():
    global _model, _tokenizer
    if _model is None:
        import torch
        from transformers import AutoModel, AutoTokenizer
        print(f"   Loading Qwen3-VL-Embedding-2B...")
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
        _model = AutoModel.from_pretrained(MODEL_PATH, trust_remote_code=True, dtype=torch.bfloat16)
        _model.eval()
        torch.set_num_threads(4)
    return _model, _tokenizer


def build_real_embeddings(meta_list: list[dict]) -> dict:
    import torch
    model, tokenizer = get_qwen_model()
    
    texts = []
    for m in meta_list:
        tags = ' '.join(m.get('tags', []))
        headings = ' '.join(m.get('headings', []))
        texts.append(f"{m['name']}\n{tags}\n{headings}\n{m.get('summary', '')}")
    
    print(f"   Encoding {len(texts)} documents...")
    instruction = "Represent this document for retrieval:"
    all_embeddings = []
    batch_size = 1  # CPU can only handle batch_size=1
    
    for i, t in enumerate(texts):
        if i % 50 == 0:
            print(f"   {i}/{len(texts)}...")
        formatted = f"{instruction}\n{t}"
        inputs = tokenizer([formatted], padding=True, truncation=True, max_length=2048, return_tensors='pt')
        with torch.no_grad():
            out = model(**inputs)
            hidden = out.last_hidden_state
            mask = inputs['attention_mask'].unsqueeze(-1).float()
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
        all_embeddings.append(pooled.numpy()[0])
    
    vectors = [emb.tolist() for emb in all_embeddings]
    dim = len(vectors[0])
    
    return {
        'type': 'real_embedding',
        'model': 'Qwen3-VL-Embedding-2B',
        'dim': dim,
        'total_docs': len(meta_list),
        'vectors': vectors,
    }


def embedding_search(query: str, index: dict, meta_list: list[dict], top_k: int = 10) -> list[dict]:
    import torch
    model, tokenizer = get_qwen_model()
    
    instruction = "Represent the query for retrieval:"
    formatted = f"{instruction}\n{query}"
    inputs = tokenizer([formatted], padding=True, truncation=True, max_length=2048, return_tensors='pt')
    with torch.no_grad():
        out = model(**inputs)
        hidden = out.last_hidden_state
        mask = inputs['attention_mask'].unsqueeze(-1).float()
        query_emb = (hidden * mask).sum(dim=1) / mask.sum(dim=1)
        query_emb = torch.nn.functional.normalize(query_emb, p=2, dim=1).numpy()[0]
    
    vectors = np.array(index['vectors'])
    scores = np.dot(vectors, query_emb)
    top_indices = np.argsort(scores)[::-1][:top_k * 2]
    
    results = []
    seen_names = set()
    for idx in top_indices:
        if idx >= len(meta_list): continue
        m = meta_list[idx]
        if m['name'] in seen_names: continue
        seen_names.add(m['name'])
        results.append({
            'name': m['name'], 'path': m['path'],
            'score': round(float(scores[idx]), 4),
            'type': 'embedding_semantic',
        })
        if len(results) >= top_k: break
    return results


# ============================================================
# CLI
# ============================================================

if __name__ == '__main__':
    meta = load_meta()
    index_path = GRAPH_DIR / 'vector_index.json'
    
    if len(sys.argv) > 1 and sys.argv[1] == '--build':
        print("🔤 Building n-gram vector index...")
        index = build_ngram_index(meta)
        index_path.write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
        print(f"✅ Index saved: {index_path}")
        print(f"   Terms: {len(index['term_index'])}, N-grams: {len(index['ngram_index'])}")
    
    elif len(sys.argv) > 1 and sys.argv[1] == '--build-real':
        print("🧠 Building REAL embedding index with Qwen3-VL-Embedding-2B...")
        print(f"   Total notes: {len(meta)}")
        index = build_real_embeddings(meta)
        index_path.write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
        print(f"✅ Embedding index saved: {index_path}")
        print(f"   Dim: {index['dim']}, Docs: {index['total_docs']}")
    
    elif len(sys.argv) > 1 and sys.argv[1] == '--search':
        query = ' '.join(sys.argv[2:])
        if not index_path.exists():
            print("⚠️  Index not built. Run with --build first.")
            sys.exit(1)
        index = json.loads(index_path.read_text(encoding='utf-8'))
        print(f"🔍 Search: '{query}'")
        
        if index.get('type') == 'real_embedding':
            results = embedding_search(query, index, meta[:index['total_docs']])
        else:
            results = ngram_search(query, index, meta[:index['total_docs']])
        
        for i, r in enumerate(results):
            print(f"  {i+1}. [{r['score']}] {r['name']}")
            print(f"     {r['path']}")
    
    else:
        print("Usage:")
        print("  python vector_index.py --build           # Build n-gram index (fast)")
        print("  python vector_index.py --build-real      # Build real embedding index (needs GPU)")
        print("  python vector_index.py --search <query>  # Search")
