from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.schema import QueryContext
from src.retriever import retrieve

ctx = QueryContext(
    product_id="CAR-001",
    product_title_en="Maxi-Cosi Pria 85 Convertible Car Seat",
    product_title_ar="كرسي سيارة ماكسي كوزي",
    category="car_seats",
    brand="Maxi-Cosi",
    child_age_months=8,
    vehicle_model="Toyota Yaris 2018"
)

result = retrieve(ctx)
print(f"Status: {result.status}")
print(f"Chunks: {len(result.chunks)}")
for c in result.chunks[:3]:
    print(f"  [{c.source}] sim={c.similarity} | {c.text[:80]}...")