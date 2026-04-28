import chromadb
from sentence_transformers import SentenceTransformer
from dataclasses import dataclass
from typing import Optional
from src.schema import QueryContext

MODEL_NAME = "intfloat/multilingual-e5-large"
_embedder: Optional[SentenceTransformer] = None
_client: Optional[chromadb.PersistentClient] = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(MODEL_NAME)
    return _embedder


def get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path="./chromadb_store")
    return _client


@dataclass
class RetrievedChunk:
    id: str
    text: str
    similarity: float
    metadata: dict
    source: str  # "catalog" or "returns_kb"


@dataclass
class RetrievalResult:
    status: str  # "OK" or "INSUFFICIENT_DATA"
    chunks: list[RetrievedChunk]
    catalog_count: int
    returns_count: int


def retrieve(context: QueryContext, top_k: int = 5) -> RetrievalResult:
    """
    Dual retrieval: product catalog + returns knowledge base.
    
    Uses metadata filtering to stay within the same category.
    Filters chunks below similarity threshold to avoid noise.
    """
    embedder = get_embedder()
    client = get_client()
    
    catalog_col = client.get_collection("product_catalog")
    returns_col = client.get_collection("returns_kb")
    
    # Build semantically rich queries
    catalog_query = (
        f"query: {context.category} {context.product_title_en} "
        f"compatibility age {context.child_age_months} months "
        f"vehicle {context.vehicle_model or 'unknown'}"
    )
    returns_query = (
        f"query: return reason {context.category} "
        f"{context.product_title_en} incompatible unsuitable"
    )
    
    catalog_emb = embedder.encode(catalog_query, normalize_embeddings=True).tolist()
    returns_emb = embedder.encode(returns_query, normalize_embeddings=True).tolist()
    
    # Catalog retrieval with category filter
    where_filter = {"category": context.category}
    catalog_results = catalog_col.query(
        query_embeddings=[catalog_emb],
        n_results=min(top_k, catalog_col.count()),
        where=where_filter,
        include=["documents", "distances", "metadatas"]
    )
    
    # Returns retrieval — no category filter to catch cross-category patterns
    returns_results = returns_col.query(
        query_embeddings=[returns_emb],
        n_results=min(top_k, returns_col.count()),
        include=["documents", "distances", "metadatas"]
    )
    
    # Convert distances to similarities (ChromaDB uses L2 distance by default)
    # For normalized embeddings, similarity = 1 - (distance / 2)
    SIMILARITY_THRESHOLD = 0.4
    
    all_chunks = []
    
    for i, doc in enumerate(catalog_results['documents'][0]):
        dist = catalog_results['distances'][0][i]
        sim = 1 - (dist / 2)
        if sim >= SIMILARITY_THRESHOLD:
            all_chunks.append(RetrievedChunk(
                id=catalog_results['ids'][0][i],
                text=doc,
                similarity=round(sim, 3),
                metadata=catalog_results['metadatas'][0][i],
                source="catalog"
            ))
    
    for i, doc in enumerate(returns_results['documents'][0]):
        dist = returns_results['distances'][0][i]
        sim = 1 - (dist / 2)
        if sim >= SIMILARITY_THRESHOLD:
            all_chunks.append(RetrievedChunk(
                id=returns_results['ids'][0][i],
                text=doc,
                similarity=round(sim, 3),
                metadata=returns_results['metadatas'][0][i],
                source="returns_kb"
            ))
    
    catalog_count = sum(1 for c in all_chunks if c.source == "catalog")
    returns_count = sum(1 for c in all_chunks if c.source == "returns_kb")
    
    if not all_chunks:
        return RetrievalResult(
            status="INSUFFICIENT_DATA",
            chunks=[],
            catalog_count=0,
            returns_count=0
        )
    
    catalog_chunks = [chunk for chunk in all_chunks if chunk.source == "catalog"][:4]
    returns_chunks = [chunk for chunk in all_chunks if chunk.source == "returns_kb"][:4]
    final_chunks = catalog_chunks + returns_chunks

    # Sort by similarity descending after balancing by source
    final_chunks.sort(key=lambda x: x.similarity, reverse=True)
    
    return RetrievalResult(
        status="OK",
        chunks=final_chunks,
        catalog_count=catalog_count,
        returns_count=returns_count
    )