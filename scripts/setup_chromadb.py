import json
import chromadb
from sentence_transformers import SentenceTransformer
from pathlib import Path

# Load multilingual embedding model
# Downloads ~1.1GB on first run, cached after
MODEL_NAME = "intfloat/multilingual-e5-large"
embedder = SentenceTransformer(MODEL_NAME)

# Initialize ChromaDB (persists to disk)
client = chromadb.PersistentClient(path="./chromadb_store")

# Delete existing collections if rebuilding
for name in ["product_catalog", "returns_kb"]:
    try:
        client.delete_collection(name)
    except Exception:
        pass

catalog_collection = client.create_collection("product_catalog")
returns_collection = client.create_collection("returns_kb")


def build_catalog_chunk(product: dict) -> str:
    """
    Convert a product dict to a rich text chunk for embedding.
    This is the text that gets retrieved. Make it information-dense.
    """
    return f"""
Product: {product['title_en']} | {product.get('title_ar', '')}
Category: {product['category']} | Brand: {product.get('brand', 'Unknown')}
Age range: {product['age_range']['min_months']} to {product['age_range']['max_months']} months
Compatibility: {product['compatibility_notes']}
Incompatibility signals: {', '.join(product.get('incompatibility_signals', []))}
Return risk type: {product.get('return_risk_category', 'unknown')}
Safety notes: {product.get('safety_notes', '')}
Common return reasons: {', '.join(product.get('common_return_reasons', []))}
    """.strip()


def build_returns_chunk(event: dict) -> str:
    """
    Convert a return event to a text chunk for embedding.
    """
    return f"""
Return event in category: {event['category']}
Customer complaint: {event['return_reason_raw']}
Classified as: {event['return_reason_classified']}
Was preventable: {event['was_preventable']}
Prevention signal: {event.get('prevention_signal', '')}
Resolution: {event['resolution']}
    """.strip()


def index_catalog():
    products = json.loads(Path("data/catalog.json").read_text(encoding="utf-8"))
    
    chunks = [build_catalog_chunk(p) for p in products]
    ids = [p['product_id'] for p in products]
    metadatas = [{"category": p["category"], "brand": p.get("brand", ""), 
                  "product_id": p["product_id"]} for p in products]
    
    # Prefix "query: " is required for multilingual-e5 model
    embeddings = embedder.encode(
        [f"passage: {c}" for c in chunks], 
        normalize_embeddings=True
    ).tolist()
    
    catalog_collection.add(
        documents=chunks,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas
    )
    print(f"Indexed {len(products)} products into catalog_collection")


def index_returns():
    events = json.loads(Path("data/returns_kb.json").read_text(encoding="utf-8"))
    
    chunks = [build_returns_chunk(e) for e in events]
    ids = [e['return_id'] for e in events]
    metadatas = [{"category": e["category"], 
                  "reason_type": e["return_reason_classified"]} for e in events]
    
    embeddings = embedder.encode(
        [f"passage: {c}" for c in chunks],
        normalize_embeddings=True
    ).tolist()
    
    returns_collection.add(
        documents=chunks,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas
    )
    print(f"Indexed {len(events)} return events into returns_collection")


def verify_index():
    """
    Query each collection with sample prompts and print top hit.
    Useful as a quick retrieval sanity check after indexing.
    """
    tests = {
        "product_catalog": [
            "rear-facing infant car seat for small sedan",
            "formula for babies with reflux symptoms",
            "stroller that fits airplane cabin",
        ],
        "returns_kb": [
            "customer says car seat does not fit due to no top tether",
            "formula returned because child has milk protein allergy",
            "stroller and car seat adapter did not click together",
        ],
    }

    collections = {
        "product_catalog": catalog_collection,
        "returns_kb": returns_collection,
    }

    print("\nVerifying retrieval from indexed collections...")
    for collection_name, queries in tests.items():
        collection = collections[collection_name]
        print(f"\n[{collection_name}]")

        for q in queries:
            query_embedding = embedder.encode(
                [f"query: {q}"],
                normalize_embeddings=True,
            ).tolist()

            result = collection.query(
                query_embeddings=query_embedding,
                n_results=1,
            )

            top_id = result.get("ids", [[]])[0][0] if result.get("ids") and result["ids"][0] else "N/A"
            top_distance = (
                result.get("distances", [[]])[0][0]
                if result.get("distances") and result["distances"][0]
                else None
            )
            top_document = (
                result.get("documents", [[]])[0][0]
                if result.get("documents") and result["documents"][0]
                else ""
            )

            print(f"- Query: {q}")
            if top_id == "N/A":
                print("  Top result: none")
                continue

            if top_distance is not None:
                similarity = 1.0 - (top_distance / 2.0)
                preview = (top_document[:80] + "...") if len(top_document) > 80 else top_document
                print(f"Top result: {top_id} (similarity={similarity:.3f}, source={collection_name})")
                print(f"Preview: {preview}")
            else:
                print(f"  Top result: {top_id}")


if __name__ == "__main__":
    index_catalog()
    index_returns()
    verify_index()
    print("ChromaDB setup complete. Run this once before starting the API.")