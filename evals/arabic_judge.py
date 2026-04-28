import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import OpenAI

oc = OpenAI(base_url="https://openrouter.ai/api/v1",
            api_key=Path(".env").read_text().split("OPENROUTER_API_KEY=")[1].split("\n")[0])

JUDGE_PROMPT = """You are a native Arabic speaker from the Gulf region reviewing baby product safety copy.

Rate this Arabic text on three dimensions:
1. Fluency (1-5): Does it read naturally? 5 = native speaker quality, 1 = clearly machine translated
2. Domain terminology (1-5): Are baby product and safety terms correct in Arabic?  
3. Actionability (1-5): Is the message clear and specific enough for a parent to act on?

Arabic text to evaluate:
{text}

Context (what this text should communicate):
{context}

Return JSON only, no explanation:
{{"fluency": N, "terminology": N, "actionability": N, "notes": "brief observation in English"}}"""


def judge_arabic(arabic_text: str, context: str) -> dict:
    response = oc.chat.completions.create(
        model="openai/gpt-oss-120b:free",  # stronger model for quality judging
        messages=[{
            "role": "user",
            "content": JUDGE_PROMPT.format(text=arabic_text, context=context)
        }],
        temperature=0.0,
        max_tokens=200
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except Exception:
        return {
        "fluency": 0,
        "terminology": 0,
        "actionability": 0,
        "notes": "JSON parse failed"
    }


# The 3 test cases for Arabic evaluation
ARABIC_TEST_CASES = [
    {
        "arabic_text": "",  # Fill in after running TC-01
        "context": "Car seat may be incompatible with user's vehicle. High risk. Intervention: ask user to confirm vehicle model before purchase."
    },
    {
        "arabic_text": "",  # Fill in after running TC-03
        "context": "Toy is age 3+ but user's child is 14 months. Safety risk due to small parts. High risk."
    },
    {
        "arabic_text": "",  # Fill in after running TC-04
        "context": "Formula contains dairy protein. User profile shows dairy allergy. High risk. Intervention: recommend hypoallergenic alternative."
    }
]


if __name__ == "__main__":
    print("Arabic Quality Evaluation")
    print("="*50)
    
    total_fluency = 0
    total_terminology = 0
    total_actionability = 0
    
    for i, case in enumerate(ARABIC_TEST_CASES):
        if not case["arabic_text"]:
            print(f"\nCase {i+1}: SKIPPED — fill in arabic_text from eval run")
            continue
        
        scores = judge_arabic(case["arabic_text"], case["context"])
        print(f"\nCase {i+1}:")
        print(f"  Text: {case['arabic_text']}")
        print(f"  Fluency: {scores['fluency']}/5")
        print(f"  Terminology: {scores['terminology']}/5")
        print(f"  Actionability: {scores['actionability']}/5")
        print(f"  Notes: {scores['notes']}")
        
        total_fluency += scores['fluency']
        total_terminology += scores['terminology']
        total_actionability += scores['actionability']
    
    n = len([c for c in ARABIC_TEST_CASES if c["arabic_text"]])
    if n > 0:
        print(f"\nAverage scores ({n} cases):")
        print(f"  Fluency: {total_fluency/n:.1f}/5")
        print(f"  Terminology: {total_terminology/n:.1f}/5")
        print(f"  Actionability: {total_actionability/n:.1f}/5")
        print(f"\nPASS threshold: 4.0+ on fluency")