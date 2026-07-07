#!/usr/bin/env python
"""
test_chunk_body.py — 测试段落切割逻辑
"""
import sys
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))
from build_graph import chunk_body

LONG_BODY = """## 核心概念

赛璐璐风格（Cel-Shading）是一种非真实感渲染技术，以硬轮廓线、平涂色块和块状高光为特征。
与传统的日系水彩风格不同，赛璐璐追求的是动画感而非真实感。
这种风格最早来源于日本动画产业，通过减少色彩层次和简化阴影来降低制作成本。
在现代 AI 绘画中，赛璐璐 LoRA 是最受欢迎的模型微调方向之一。
其核心优势在于角色一致性高、渲染速度快、风格辨识度强。
在商业应用中，赛璐璐风格广泛应用于游戏立绘、漫画生成、虚拟偶像等多个领域。

## 实现方案

最简单的实现方案是使用 Stable Diffusion + 赛璐璐 LoRA。
模型选择 FLUX.1 Kontext dev 作为基础模型，配合专门训练的赛璐璐风格 LoRA 权重。
也可以使用 ComfyUI 搭建工作流，通过 ControlNet 控制轮廓线。
在参数设置上，CFG scale 建议 5-7，denoising strength 0.6-0.75 效果最佳。
对于角色一致性，可以使用 IP-Adapter 配合角色参考图实现。
在实际生产环境中，通常使用多模型级联：FLUX 生成底图 → SDXL 精修 → ControlNet 固定轮廓。

## 部署架构

系统采用 Docker Compose 部署，包含三个服务：API 网关、推理引擎、任务队列。
API 网关使用 FastAPI + Uvicorn，推理引擎基于 ComfyUI，任务队列使用 Celery + Redis。
GPU 资源通过 NVIDIA MPS 实现多模型共享，峰值显存控制在 6GB 以内。
日志收集使用 ELK Stack，监控告警通过 Prometheus + Grafana 实现。
容灾方面，主服务部署在阿里云 ECS，灾备服务部署在华为云，通过 DNS 智能解析实现自动切换。
数据备份策略为每日增量 + 每周全量，备份文件加密后存储到 OSS 冷存储。"""

def test_chunk_by_headings():
    """按 ## 标题分段"""
    chunks = chunk_body(LONG_BODY, headings=["核心概念", "实现方案", "部署架构"])
    assert len(chunks) >= 2, f"Expected ≥2 chunks, got {len(chunks)}"

def test_chunk_has_id():
    """每个 chunk 有 id"""
    chunks = chunk_body(LONG_BODY, headings=[])
    for c in chunks:
        assert "id" in c, f"Missing id in chunk: {c}"
        assert "text" in c, f"Missing text in chunk: {c}"
        assert "note_name" in c, f"Missing note_name in chunk: {c}"

def test_chunk_note_name():
    """chunk 的 note_name 可指定"""
    chunks = chunk_body(LONG_BODY, headings=[], name="test-note")
    assert len(chunks) >= 1
    assert chunks[0]["note_name"] == "test-note"

def test_markdown_cleaned():
    """Markdown 输入不崩溃，代码块被清洗"""
    md_text = "## Test\n\nSome text here.\n\n```python\nprint('hello')\n```\n\nMore text after code block."
    chunks = chunk_body(md_text, headings=[])
    # 可能因太短不产 chunk，但不应崩溃
    if chunks:
        cleaned = chunks[0]["text"]
        assert "```" not in cleaned, "code block not cleaned"

def test_short_sections_skipped():
    """过短的段落被跳过"""
    short = "## Short\nabc"
    chunks = chunk_body(short, headings=[])
    assert len(chunks) == 0

def test_oversized_split():
    """超长段落被切分"""
    long_text = "## Long\n" + "赛璐璐渲染技术详解。" * 300  # 300 × 9 = 2700 chars
    chunks = chunk_body(long_text, headings=[])
    assert len(chunks) >= 2, f"Expected ≥2 chunks, got {len(chunks)}"

def test_content_integrity():
    """切割后内容不丢失"""
    chunks = chunk_body(LONG_BODY, headings=[])
    all_text = "".join(c["text"] for c in chunks)
    assert "赛璐璐" in all_text, "key content lost"
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
