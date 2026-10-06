#!/usr/bin/env python
"""
test_chunk_body.py — tests section chunking logic
"""
import sys
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))
from build_graph import chunk_body

LONG_BODY = """## \u6838\u5fc3\u6982\u5ff5

\u98ce\u683c\u5316\u6e32\u67d3\uff08Cel-Shading\uff09\u662f\u4e00\u79cd\u975e\u771f\u5b9e\u611f\u6e32\u67d3\u6280\u672f\uff0c\u4ee5\u786c\u8f6e\u5ed3\u7ebf\u3001\u5e73\u6d82\u8272\u5757\u548c\u5757\u72b6\u9ad8\u5149\u4e3a\u7279\u5f81\u3002
\u4e0e\u4f20\u7edf\u7684\u65e5\u7cfb\u6c34\u5f69\u98ce\u683c\u4e0d\u540c\uff0c\u98ce\u683c\u5316\u6e32\u67d3\u8ffd\u6c42\u7684\u662f\u52a8\u753b\u611f\u800c\u975e\u771f\u5b9e\u611f\u3002
\u8fd9\u79cd\u98ce\u683c\u6700\u65e9\u6765\u6e90\u4e8e\u65e5\u672c\u52a8\u753b\u4ea7\u4e1a\uff0c\u901a\u8fc7\u51cf\u5c11\u8272\u5f69\u5c42\u6b21\u548c\u7b80\u5316\u9634\u5f71\u6765\u964d\u4f4e\u5236\u4f5c\u6210\u672c\u3002
\u5728\u73b0\u4ee3 AI \u7ed8\u753b\u4e2d\uff0c\u98ce\u683c\u5316\u6e32\u67d3 LoRA \u662f\u6700\u53d7\u6b22\u8fce\u7684\u6a21\u578b\u5fae\u8c03\u65b9\u5411\u4e4b\u4e00\u3002
\u5176\u6838\u5fc3\u4f18\u52bf\u5728\u4e8e\u89d2\u8272\u4e00\u81f4\u6027\u9ad8\u3001\u6e32\u67d3\u901f\u5ea6\u5feb\u3001\u98ce\u683c\u8fa8\u8bc6\u5ea6\u5f3a\u3002
\u5728\u5546\u4e1a\u5e94\u7528\u4e2d\uff0c\u98ce\u683c\u5316\u6e32\u67d3\u5e7f\u6cdb\u5e94\u7528\u4e8e\u6e38\u620f\u7acb\u7ed8\u3001\u6f2b\u753b\u751f\u6210\u3001\u865a\u62df\u5076\u50cf\u7b49\u591a\u4e2a\u9886\u57df\u3002

## \u5b9e\u73b0\u65b9\u6848

\u6700\u7b80\u5355\u7684\u5b9e\u73b0\u65b9\u6848\u662f\u4f7f\u7528 Stable Diffusion + \u98ce\u683c\u5316\u6e32\u67d3 LoRA\u3002
\u6a21\u578b\u9009\u62e9 FLUX.1 Kontext dev \u4f5c\u4e3a\u57fa\u7840\u6a21\u578b\uff0c\u914d\u5408\u4e13\u95e8\u8bad\u7ec3\u7684\u98ce\u683c\u5316\u6e32\u67d3 LoRA \u6743\u91cd\u3002
\u4e5f\u53ef\u4ee5\u4f7f\u7528 ComfyUI \u642d\u5efa\u5de5\u4f5c\u6d41\uff0c\u901a\u8fc7 ControlNet \u63a7\u5236\u8f6e\u5ed3\u7ebf\u3002
\u5728\u53c2\u6570\u8bbe\u7f6e\u4e0a\uff0cCFG scale \u5efa\u8bae 5-7\uff0cdenoising strength 0.6-0.75 \u6548\u679c\u6700\u4f73\u3002
\u5bf9\u4e8e\u89d2\u8272\u4e00\u81f4\u6027\uff0c\u53ef\u4ee5\u4f7f\u7528 IP-Adapter \u914d\u5408\u89d2\u8272\u53c2\u8003\u56fe\u5b9e\u73b0\u3002
\u5728\u5b9e\u9645\u751f\u4ea7\u73af\u5883\u4e2d\uff0c\u901a\u5e38\u4f7f\u7528\u591a\u6a21\u578b\u7ea7\u8054\uff1aFLUX \u751f\u6210\u5e95\u56fe → SDXL \u7cbe\u4fee → ControlNet \u56fa\u5b9a\u8f6e\u5ed3\u3002

## \u90e8\u7f72\u67b6\u6784

\u7cfb\u7edf\u91c7\u7528 Docker Compose \u90e8\u7f72\uff0c\u5305\u542b\u4e09\u4e2a\u670d\u52a1\uff1aAPI \u7f51\u5173\u3001\u63a8\u7406\u5f15\u64ce\u3001\u4efb\u52a1\u961f\u5217\u3002
API \u7f51\u5173\u4f7f\u7528 FastAPI + Uvicorn\uff0c\u63a8\u7406\u5f15\u64ce\u57fa\u4e8e ComfyUI\uff0c\u4efb\u52a1\u961f\u5217\u4f7f\u7528 Celery + Redis\u3002
GPU \u8d44\u6e90\u901a\u8fc7 NVIDIA MPS \u5b9e\u73b0\u591a\u6a21\u578b\u5171\u4eab\uff0c\u5cf0\u503c\u663e\u5b58\u63a7\u5236\u5728 6GB \u4ee5\u5185\u3002
\u65e5\u5fd7\u6536\u96c6\u4f7f\u7528 ELK Stack\uff0c\u76d1\u63a7\u544a\u8b66\u901a\u8fc7 Prometheus + Grafana \u5b9e\u73b0\u3002
\u5bb9\u707e\u65b9\u9762\uff0c\u4e3b\u670d\u52a1\u90e8\u7f72\u5728\u963f\u91cc\u4e91 ECS\uff0c\u707e\u5907\u670d\u52a1\u90e8\u7f72\u5728\u534e\u4e3a\u4e91\uff0c\u901a\u8fc7 DNS \u667a\u80fd\u89e3\u6790\u5b9e\u73b0\u81ea\u52a8\u5207\u6362\u3002
\u6570\u636e\u5907\u4efd\u7b56\u7565\u4e3a\u6bcf\u65e5\u589e\u91cf + \u6bcf\u5468\u5168\u91cf\uff0c\u5907\u4efd\u6587\u4ef6\u52a0\u5bc6\u540e\u5b58\u50a8\u5230 OSS \u51b7\u5b58\u50a8\u3002"""

def test_chunk_by_headings():
    """chunks split by ## headings"""
    chunks = chunk_body(LONG_BODY, headings=["\u6838\u5fc3\u6982\u5ff5", "\u5b9e\u73b0\u65b9\u6848", "\u90e8\u7f72\u67b6\u6784"])
    assert len(chunks) >= 2, f"Expected ≥2 chunks, got {len(chunks)}"

def test_chunk_has_id():
    """each chunk has an id"""
    chunks = chunk_body(LONG_BODY, headings=[])
    for c in chunks:
        assert "id" in c, f"Missing id in chunk: {c}"
        assert "text" in c, f"Missing text in chunk: {c}"
        assert "note_name" in c, f"Missing note_name in chunk: {c}"

def test_chunk_note_name():
    """chunk note_name can be specified"""
    chunks = chunk_body(LONG_BODY, headings=[], name="test-note")
    assert len(chunks) >= 1
    assert chunks[0]["note_name"] == "test-note"

def test_markdown_cleaned():
    """markdown input does not crash, code blocks are cleaned"""
    md_text = "## Test\n\nSome text here.\n\n```python\nprint('hello')\n```\n\nMore text after code block."
    chunks = chunk_body(md_text, headings=[])
    # may produce no chunk because it is too short, but must not crash
    if chunks:
        cleaned = chunks[0]["text"]
        assert "```" not in cleaned, "code block not cleaned"

def test_short_sections_skipped():
    """overly short sections are skipped"""
    short = "## Short\nabc"
    chunks = chunk_body(short, headings=[])
    assert len(chunks) == 0

def test_oversized_split():
    """overly long sections are split"""
    long_text = "## Long\n" + "\u98ce\u683c\u5316\u6e32\u67d3\u6280\u672f\u8be6\u89e3\u3002" * 300  # 300 × 9 = 2700 chars
    chunks = chunk_body(long_text, headings=[])
    assert len(chunks) >= 2, f"Expected ≥2 chunks, got {len(chunks)}"

def test_content_integrity():
    """no content lost after chunking"""
    chunks = chunk_body(LONG_BODY, headings=[])
    all_text = "".join(c["text"] for c in chunks)
    assert "\u98ce\u683c\u5316\u6e32\u67d3" in all_text, "key content lost"
    assert "FLUX.1" in all_text, "model name lost"

if __name__ == "__main__":
    tests = [test_chunk_by_headings, test_chunk_has_id, test_chunk_note_name,
             test_markdown_cleaned, test_short_sections_skipped,
             test_oversized_split, test_content_integrity]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ✅ {t.__name__}")
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:
            print(f"  💥 {t.__name__}: {e}")
    print(f"\n  {passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
