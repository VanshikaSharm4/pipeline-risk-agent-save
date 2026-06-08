"""Track B — local ChromaDB on log chunks (optional deps)."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

import config


def _vector_available() -> bool:
    try:
        import chromadb  # noqa: F401
        from sentence_transformers import SentenceTransformer  # noqa: F401
        return True
    except ImportError:
        return False


def _chunk_text(text: str, max_len: int = 500) -> List[str]:
    if not text or text.startswith("ERROR:"):
        return []
    chunks = []
    for line in text.splitlines():
        line = line.strip()
        if len(line) < 20:
            continue
        if any(k in line.lower() for k in ("error", "fail", "exception", "warn", "crxde", "npm")):
            chunks.append(line[:max_len])
    return chunks[:20]


def build_index(profiles: List[Dict[str, Any]]) -> int:
    if not config.ENABLE_VECTOR_TRACK or not _vector_available():
        return 0

    import chromadb
    from chromadb.utils import embedding_functions

    config.VECTOR_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(config.VECTOR_PERSIST_DIR))
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=config.EMBEDDING_MODEL
    )

    try:
        client.delete_collection("pipeline_logs")
    except Exception:
        pass

    coll = client.create_collection("pipeline_logs", embedding_function=ef)
    ids, docs, metas = [], [], []
    for prof in profiles:
        eid = prof["execution_id"]
        text = prof.get("_log_text", "")
        for i, chunk in enumerate(_chunk_text(text)):
            cid = hashlib.md5(f"{eid}:{i}:{chunk[:80]}".encode()).hexdigest()
            ids.append(cid)
            docs.append(chunk)
            is_prod = prof.get("pipeline_id") == config.PIPELINE_ID_PROD
            failed = prof.get("status", "") in config.FAILED_STATUSES
            metas.append({
                "execution_id": eid,
                "pipeline_id": prof.get("pipeline_id", 0),
                "status": prof.get("status", ""),
                "is_prod": is_prod,
                "prod_failed": is_prod and failed,
                "failed_step": prof.get("failed_step") or "",
            })

    if ids:
        coll.add(ids=ids, documents=docs, metadatas=metas)
    return len(ids)


def query_similar(log_text: str, top_k: Optional[int] = None) -> Dict[str, Any]:
    k = top_k or config.VECTOR_TOP_K
    if not config.ENABLE_VECTOR_TRACK or not _vector_available():
        return {"prob": 0.0, "risk": "Low", "confidence": "low", "drivers": [], "n_samples": 0}

    chunks = _chunk_text(log_text)
    if not chunks:
        return {"prob": 0.0, "risk": "Low", "confidence": "low", "drivers": [], "n_samples": 0}

    import chromadb
    from chromadb.utils import embedding_functions

    client = chromadb.PersistentClient(path=str(config.VECTOR_PERSIST_DIR))
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=config.EMBEDDING_MODEL
    )
    try:
        coll = client.get_collection("pipeline_logs", embedding_function=ef)
    except Exception:
        return {"prob": 0.0, "risk": "Low", "confidence": "low", "drivers": ["Vector index not built"], "n_samples": 0}

    res = coll.query(query_texts=[chunks[0]], n_results=k)
    metas = (res.get("metadatas") or [[]])[0]
    if not metas:
        return {"prob": 0.0, "risk": "Low", "confidence": "low", "drivers": [], "n_samples": 0}

    failed = sum(1 for m in metas if m.get("prod_failed") or (m.get("is_prod") and m.get("status") in config.FAILED_STATUSES))
    prob = failed / len(metas)
    risk = "High" if prob >= 0.6 else "Medium" if prob >= 0.35 else "Low"
    drivers = [
        f"[VECTOR] Neighbor {m.get('execution_id')} status={m.get('status')} step={m.get('failed_step')}"
        for m in metas[:5]
    ]
    conf = "medium" if len(metas) >= 5 else "low"
    return {
        "prob": round(prob, 4),
        "risk": risk,
        "confidence": conf,
        "drivers": drivers,
        "n_samples": len(metas),
    }
