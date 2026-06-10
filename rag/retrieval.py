"""Retrieval: query one or more LanceDB knowledge bases via LlamaIndex."""

import sys
from pathlib import Path
from typing import Sequence

import lancedb

from llama_index.core import VectorStoreIndex, Settings
from llama_index.core.llms import MockLLM
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.core.storage.storage_context import StorageContext
from llama_index.embeddings.ollama import OllamaEmbedding

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import LANCEDB_DIR, DEFAULT_OLLAMA_BASE, DEFAULT_EMBED_MODEL, kb_table_name

TOP_K = 6


def _get_index(kb_name: str, embed_model: str, ollama_base: str) -> VectorStoreIndex:
    embedding = OllamaEmbedding(model_name=embed_model, base_url=ollama_base)
    Settings.embed_model = embedding
    Settings.llm = MockLLM()  # silences "LLM explicitly disabled" warning; never called

    vector_store = LanceDBVectorStore(
        uri=LANCEDB_DIR,
        table_name=kb_table_name(kb_name),
    )
    storage_ctx = StorageContext.from_defaults(vector_store=vector_store)
    return VectorStoreIndex.from_vector_store(
        vector_store, storage_context=storage_ctx
    )


def retrieve(
    query: str,
    kb_names: Sequence[str],
    embed_model: str = DEFAULT_EMBED_MODEL,
    ollama_base: str = DEFAULT_OLLAMA_BASE,
    top_k: int = TOP_K,
) -> str:
    """
    Retrieve the most relevant chunks from all selected knowledge bases.
    Returns a single formatted context string suitable for passing to an LLM.
    """
    if not kb_names:
        return "No knowledge bases selected."

    db = lancedb.connect(LANCEDB_DIR)
    existing_tables = set(db.table_names())
    available = [
        kb for kb in kb_names if kb_table_name(kb) in existing_tables
    ]
    if not available:
        return "None of the selected knowledge bases have been indexed yet."

    all_nodes = []
    for kb_name in available:
        try:
            index = _get_index(kb_name, embed_model, ollama_base)
            retriever = VectorIndexRetriever(index=index, similarity_top_k=top_k)
            nodes = retriever.retrieve(query)
            for node in nodes:
                node.node.metadata["kb_name"] = kb_name
            all_nodes.extend(nodes)
        except Exception as exc:
            all_nodes.append(
                type("FakeNode", (), {
                    "node": type("N", (), {
                        "text": f"[Error retrieving from '{kb_name}': {exc}]",
                        "metadata": {"kb_name": kb_name},
                    })(),
                    "score": 0.0,
                })()
            )

    # Sort all nodes by score descending, keep best top_k * len(kbs) overall
    all_nodes.sort(key=lambda n: n.score or 0.0, reverse=True)

    sections = []
    for i, node in enumerate(all_nodes, 1):
        kb = node.node.metadata.get("kb_name", "unknown")
        source = node.node.metadata.get("filename", "unknown")
        score = node.score or 0.0
        text = node.node.text.strip()
        sections.append(
            f"--- [Source {i}: {source} | KB: {kb} | relevance: {score:.3f}] ---\n{text}"
        )

    return "\n\n".join(sections) if sections else "No relevant content found."
