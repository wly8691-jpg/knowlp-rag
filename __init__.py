"""
KnowLP-RAG: Dual knowledge graph retrieval for Obsidian vaults.

Key components:
  - build_graph: Build dual graph from markdown notes
  - knowlp_search: P/S-Agent graph search + chunk matching
  - run_eval: Evaluate retrieval quality (P@5, R@5, MRR)
  - apply_feedback: Edge weight optimization via feedback loop
"""

__version__ = "3.0.0"
