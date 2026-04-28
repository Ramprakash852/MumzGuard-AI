# from pathlib import Path
# import sys

# sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# from src.schema import QueryContext
# from src.retriever import retrieve

# ctx = QueryContext(
#     product_id="CAR-001",
#     product_title_en="Maxi-Cosi Pria 85 Convertible Car Seat",
#     product_title_ar="كرسي سيارة ماكسي كوزي",
#     category="car_seats",
#     brand="Maxi-Cosi",
#     child_age_months=8,
#     vehicle_model="Toyota Yaris 2018"
# )

# result = retrieve(ctx)
# print(f"Status: {result.status}")
# print(f"Chunks: {len(result.chunks)}")
# for c in result.chunks[:3]:
#     print(f"  [{c.source}] sim={c.similarity} | {c.text[:80]}...")


from pathlib import Path
import sys
from dotenv import load_dotenv
import os

# Ensure project root is on sys.path when running tests from /tests
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openai import OpenAI
from src.schema import QueryContext
from src.chain import analyze_return_risk

load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")
print("API KEY:", API_KEY)

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=API_KEY)


def main():
    ctx = QueryContext(
        product_id="CAR-001",
        product_title_en="Maxi-Cosi Pria 85 Convertible Car Seat",
        product_title_ar="كرسي سيارة ماكسي كوزي",
        category="car_seats",
        brand="Maxi-Cosi",
        child_age_months=8,
        vehicle_model="Toyota Yaris 2018",
        cart_contents=[],
        has_allergies=[],
        language_preference="en",
    )

    output, failure = analyze_return_risk(ctx, client)
    if failure:
        print("Analysis failed:", failure.model_dump())
    else:
        print("Analysis succeeded:")
        print(output.model_dump_json(indent=2))


if __name__ == "__main__":
    main()