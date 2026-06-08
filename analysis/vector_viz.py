"""Inspect and visualize ChromaDB vector index."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import config


def _available() -> bool:
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


def get_collection_stats() -> Dict[str, Any]:
    if not _available() or not config.VECTOR_PERSIST_DIR.exists():
        return {"available": False, "count": 0, "message": "Vector index not built"}

    import chromadb
    from chromadb.utils import embedding_functions

    client = chromadb.PersistentClient(path=str(config.VECTOR_PERSIST_DIR))
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=config.EMBEDDING_MODEL
    )
    try:
        coll = client.get_collection("pipeline_logs", embedding_function=ef)
    except Exception as e:
        return {"available": False, "count": 0, "message": str(e)}

    data = coll.get(include=["metadatas", "documents"], limit=5000)
    ids = data.get("ids") or []
    metas = data.get("metadatas") or []
    docs = data.get("documents") or []

    by_exec: Dict[str, int] = {}
    by_step: Dict[str, int] = {}
    prod_fail = 0
    for m in metas:
        eid = m.get("execution_id", "?")
        by_exec[eid] = by_exec.get(eid, 0) + 1
        step = m.get("failed_step") or "unknown"
        by_step[step] = by_step.get(step, 0) + 1
        if m.get("prod_failed"):
            prod_fail += 1

    rows = []
    for i, doc in enumerate(docs[:200]):
        m = metas[i] if i < len(metas) else {}
        rows.append({
            "id": ids[i] if i < len(ids) else "",
            "execution_id": m.get("execution_id"),
            "pipeline_id": m.get("pipeline_id"),
            "status": m.get("status"),
            "prod_failed": m.get("prod_failed"),
            "failed_step": m.get("failed_step"),
            "snippet": (doc or "")[:120],
        })

    return {
        "available": True,
        "count": len(ids),
        "unique_executions": len(by_exec),
        "prod_failed_chunks": prod_fail,
        "by_step": by_step,
        "sample_rows": rows,
    }


def get_embeddings_2d(limit: int = 300) -> Dict[str, Any]:
    """PCA projection of embeddings for scatter plot."""
    if not _available():
        return {"points": [], "message": "chromadb not installed"}

    import chromadb
    import numpy as np
    from chromadb.utils import embedding_functions

    try:
        from sklearn.decomposition import PCA
    except ImportError:
        return {"points": [], "message": "pip install scikit-learn for 2D plot"}

    client = chromadb.PersistentClient(path=str(config.VECTOR_PERSIST_DIR))
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=config.EMBEDDING_MODEL
    )
    try:
        coll = client.get_collection("pipeline_logs", embedding_function=ef)
    except Exception as e:
        return {"points": [], "message": str(e)}

    data = coll.get(
        include=["embeddings", "metadatas"],
        limit=limit,
    )
    embs = data.get("embeddings") or []
    metas = data.get("metadatas") or []
    if not embs:
        return {"points": [], "message": "No embeddings stored"}

    X = np.array(embs)
    if X.shape[0] < 3:
        return {"points": [], "message": "Need at least 3 chunks"}

    xy = PCA(n_components=2).fit_transform(X)
    points = []
    for i, (x, y) in enumerate(xy):
        m = metas[i] if i < len(metas) else {}
        points.append({
            "x": float(x),
            "y": float(y),
            "execution_id": m.get("execution_id", ""),
            "prod_failed": bool(m.get("prod_failed")),
            "status": m.get("status", ""),
        })
    return {"points": points, "message": "ok"}


def probe_query(query_text: str, top_k: int = 10) -> List[Dict[str, Any]]:
    if not _available() or not query_text.strip():
        return []

    import chromadb
    from chromadb.utils import embedding_functions

    client = chromadb.PersistentClient(path=str(config.VECTOR_PERSIST_DIR))
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=config.EMBEDDING_MODEL
    )
    try:
        coll = client.get_collection("pipeline_logs", embedding_function=ef)
    except Exception:
        return []

    res = coll.query(
        query_texts=[query_text.strip()],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    rows = []
    for i, doc in enumerate(docs):
        m = metas[i] if i < len(metas) else {}
        rows.append({
            "distance": round(dists[i], 4) if i < len(dists) else None,
            "execution_id": m.get("execution_id"),
            "status": m.get("status"),
            "prod_failed": m.get("prod_failed"),
            "failed_step": m.get("failed_step"),
            "snippet": (doc or "")[:200],
        })
    return rows
