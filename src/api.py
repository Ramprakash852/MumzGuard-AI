import json
import logging
import os
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel
from typing import Optional

from src.schema import QueryContext, ReturnRiskOutput
from src.chain import analyze_return_risk

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize clients once at startup
openrouter_client: Optional[OpenAI] = None


def _load_openrouter_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip().strip('"').strip("'")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is missing or empty")
    return api_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    global openrouter_client
    # ✅ CHANGED: initialize OpenRouter only; Anthropic removed completely
    openrouter_client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=_load_openrouter_api_key()
    )
    logger.info("Clients initialized")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="MumzGuard Return Risk API",
    description="Predicts return risk for baby products before checkout",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Validation failure log
FAILURE_LOG = Path("logs/validation_failures.jsonl")
FAILURE_LOG.parent.mkdir(exist_ok=True)


class RiskRequest(BaseModel):
    product_id: str
    product_title_en: str
    product_title_ar: Optional[str] = None
    category: str
    brand: Optional[str] = None
    child_age_months: Optional[int] = None
    vehicle_model: Optional[str] = None
    cart_contents: list[str] = []
    has_allergies: list[str] = []
    language_preference: str = "en"


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/analyze", response_model=ReturnRiskOutput)
async def analyze(request: RiskRequest):
    context = QueryContext(**request.model_dump())
    
    # ✅ CHANGED: OpenRouter-only analysis call
    output, failure = analyze_return_risk(context, openrouter_client)
    
    if failure:
        # Log failure for debugging
        with open(FAILURE_LOG, "a") as f:
            f.write(failure.model_dump_json() + "\n")
        raise HTTPException(
            status_code=422,
            detail=f"Analysis failed: {failure.error_type} — {failure.error_detail}"
        )
    
    return output


@app.get("/products")
async def list_products():
    """Returns the product catalog for the frontend to display."""
    import json
    from pathlib import Path
    # ✅ CHANGED: force UTF-8 so Arabic product titles load on Windows
    products = json.loads(Path("data/catalog.json").read_text(encoding="utf-8"))
    return {"products": products, "count": len(products)}


@app.get("/products/{product_id}")
async def get_product(product_id: str):
    import json
    from pathlib import Path
    # ✅ CHANGED: force UTF-8 so Arabic product titles load on Windows
    products = json.loads(Path("data/catalog.json").read_text(encoding="utf-8"))
    product = next((p for p in products if p["product_id"] == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product