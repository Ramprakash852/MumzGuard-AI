import json
import sys
import time
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import OpenAI
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from src.schema import QueryContext
from src.chain import analyze_return_risk

console = Console()

# Load test cases
TEST_CASES = json.loads(Path("evals/test_cases.json").read_text())

# Initialize clients
oc = OpenAI(base_url="https://openrouter.ai/api/v1", 
            api_key=Path(".env").read_text().split("OPENROUTER_API_KEY=")[1].split("\n")[0])


def score_test_case(result, failure, test_case: dict) -> dict:
    """
    Score a test case on a 10-point rubric.
    Returns {"score": N, "max": 10, "breakdown": {...}, "pass": bool}
    """
    if failure or result is None:
        return {
            "score": 0, "max": 10,
            "breakdown": {"schema_valid": False, "notes": str(failure)},
            "pass": False
        }
    
    score = 0
    breakdown = {}
    
    expected = test_case.get("expected_risk_level")
    key_check = test_case.get("key_check", "")
    
    # Schema validates (2 pts)
    breakdown["schema_valid"] = True
    score += 2
    
    # Risk level correct (3 pts)
    if expected == "not_LOW":
        correct = result.risk_level.value != "LOW"
    elif expected:
        correct = result.risk_level.value == expected
    else:
        correct = True
    breakdown["risk_level_correct"] = correct
    if correct:
        score += 3
    
    # Intervention present iff HIGH/MEDIUM (2 pts)
    if result.risk_level.value in ("HIGH", "MEDIUM"):
        has_intervention = bool(result.intervention_en) and bool(result.intervention_ar)
        breakdown["intervention_correct"] = has_intervention
        if has_intervention:
            score += 2
    else:
        breakdown["intervention_correct"] = result.intervention_en is None
        if result.intervention_en is None:
            score += 2
    
    # Arabic non-empty (1 pt)
    arabic_ok = bool(result.risk_reason_ar) and len(result.risk_reason_ar) > 5
    breakdown["arabic_present"] = arabic_ok
    if arabic_ok:
        score += 1
    
    # Confidence reasonable (1 pt)
    # INSUFFICIENT_DATA should have confidence 0
    if result.risk_level.value == "INSUFFICIENT_DATA":
        conf_ok = result.confidence <= 0.1
    else:
        conf_ok = result.confidence > 0.0
    breakdown["confidence_reasonable"] = conf_ok
    if conf_ok:
        score += 1
    
    # Refusal for unknown SKU (1 pt)
    if "UNKNOWN" in test_case["input"].get("product_id", ""):
        refusal_ok = result.refuses_if_no_data
        breakdown["refusal_correct"] = refusal_ok
        if refusal_ok:
            score += 1
    else:
        breakdown["refusal_correct"] = "n/a"
        score += 1
    
    return {
        "score": score,
        "max": 10,
        "breakdown": breakdown,
        "pass": score >= 7,
        "result": result.model_dump() if result else None
    }


def run_all_evals():
    console.print("\n[bold]MumzGuard Evaluation Harness[/bold]")
    console.print(f"Running {len(TEST_CASES)} test cases...\n")
    
    results = []
    
    for tc in TEST_CASES:
        console.print(f"[dim]Running {tc['id']}: {tc['label']}...[/dim]", end="")
        
        inp = tc["input"]
        context = QueryContext(
            product_id=inp.get("product_id", "UNKNOWN"),
            product_title_en=inp.get("product_title_en", "Unknown Product"),
            product_title_ar=inp.get("product_title_ar"),
            category=inp.get("category", "unknown"),
            brand=inp.get("brand"),
            child_age_months=inp.get("child_age_months"),
            vehicle_model=inp.get("vehicle_model"),
            cart_contents=inp.get("cart_contents", []),
            has_allergies=inp.get("has_allergies", []),
            language_preference=inp.get("language_preference", "en")
        )
        
        try:
            output, failure = analyze_return_risk(context, oc)
        except Exception as e:
            output, failure = None, str(e)
        
        scored = score_test_case(output, failure, tc)
        scored["test_id"] = tc["id"]
        scored["label"] = tc["label"]
        results.append(scored)
        
        status = "[green]PASS[/green]" if scored["pass"] else "[red]FAIL[/red]"
        console.print(f" {status} ({scored['score']}/{scored['max']})")
        
        time.sleep(0.5)  # Be gentle on API rate limits
    
    # Summary table
    table = Table(title="\nEval Results Summary")
    table.add_column("ID", style="dim")
    table.add_column("Label")
    table.add_column("Score")
    table.add_column("Pass")
    
    total_score = 0
    total_max = 0
    passed = 0
    
    for r in results:
        status = "✓" if r["pass"] else "✗"
        color = "green" if r["pass"] else "red"
        table.add_row(
            r["test_id"],
            r["label"][:50] + ("..." if len(r["label"]) > 50 else ""),
            f"{r['score']}/{r['max']}",
            f"[{color}]{status}[/{color}]"
        )
        total_score += r["score"]
        total_max += r["max"]
        if r["pass"]:
            passed += 1
    
    console.print(table)
    
    pct = (total_score / total_max) * 100
    console.print(f"\n[bold]Total: {total_score}/{total_max} ({pct:.1f}%)[/bold]")
    console.print(f"Passed: {passed}/{len(results)}")
    
    # Save results
    output_path = Path("evals/results") / f"eval_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2, default=str))
    console.print(f"\nResults saved to {output_path}")
    
    return results


if __name__ == "__main__":
    run_all_evals()