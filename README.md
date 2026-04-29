# 🛡️ MumzGuard – AI Return Risk Intelligence System

MumzGuard is an AI-powered return risk intelligence system designed for Mumzworld to help mothers make safer, more informed purchase decisions before checkout. It analyzes product details alongside user context (such as child age, allergies, and vehicle compatibility) using a retrieval-augmented pipeline and large language models to predict the likelihood of returns. The system generates structured, multilingual (English and Arabic) outputs including risk level, reasoning, and actionable interventions, enabling a more personalized and trustworthy shopping experience while reducing operational costs from returns.

---

## 🎬 Quick Start

- **📹 3-minute video walkthrough:** [Watch on Loom](https://loom.com/share/your-loom-link-here)
- **📊 Evaluation report:** [EVALS.md](./evals.md) — 12 test cases, 79.2% pass rate, detailed failure analysis
- **⚖️ Architecture & tradeoffs:** [TRADEOFFS.md](./TRADEOFFS.md) — why RAG, why these models, what was cut

---

# ⚙️ 2. Setup & Run (UNDER 5 MINUTES)

1. Clone repository

```bash
git clone https://github.com/Ramprakash852/MumzGuard-AI.git
cd MumzGuard-AI
```

2. Create virtual environment

```bash
python -m venv .venv
```

3. Activate virtual environment (Windows PowerShell)

```powershell
.\.venv\Scripts\Activate.ps1
```

4. Install dependencies

```bash
pip install -r requirements.txt
```

5. Set OpenRouter API key (.env file)

```bash
echo OPENROUTER_API_KEY=your_openrouter_api_key > .env
```

6. Optional one-time indexing (skip if chromadb_store already exists and is populated)

```bash
python scripts/setup_chromadb.py
```

7. Run backend API (FastAPI)

```bash
uvicorn src.api:app --reload --port 8000
```

8. Run frontend UI (new terminal)

```bash
streamlit run frontend/app.py
```

9. Open:
- API: http://127.0.0.1:8000/docs
- UI: http://localhost:8501

---

# 🏗️ 3. System Architecture

MumzGuard uses a staged, fail-safe architecture:

- Retriever (ChromaDB + multilingual embeddings):
  - Uses intfloat/multilingual-e5-large embeddings.
  - Queries two collections: product catalog and returns knowledge base.
  - Applies category filtering for catalog retrieval and similarity thresholding.
- Grading step:
  - A lightweight LLM relevance classifier filters retrieved chunks.
  - Keeps only context that is actionable for return-risk reasoning.
- Reasoning step (with fallback):
  - Primary reasoning model runs first.
  - If unavailable/error-prone, fallback model is used with retry/backoff rules.
- JSON validation:
  - Strict schema validation enforces risk bands, Arabic output quality checks, intervention requirements, and numeric ranges.
  - Parse failures and schema failures are logged and returned safely.
- Frontend display:
  - Streamlit UI shows risk level, score, confidence, reasons (EN/AR), intervention, and evidence sources.

Simple flow:

User → Retriever → Grading → Reasoning → Output

---

# 🤖 4. Model & Tooling Choices

Models used:

- Grading model:
  - openai/gpt-oss-120b:free
  - Role: chunk relevance classification (keep/drop context)
- Reasoning models (fallback chain):
  - openai/gpt-oss-120b:free (primary)
  - nvidia/nemotron-3-super:free (fallback)
  - Role: generate final risk assessment JSON

Why these choices:

- Reasoning quality: GPT-OSS provided stronger structured reasoning and stable JSON behavior.
- Availability: Both models are accessible through OpenRouter with a unified client path.
- Cost: Free-tier models enabled fast iteration for an internship constraint while preserving quality.

OpenRouter usage:

- OpenAI-compatible API client with base URL routing.
- Single API-key integration simplified backend setup and model fallback management.

What worked:

- Strict Pydantic validation significantly reduced silent bad outputs.
- Model fallback improved resilience during model-specific failures.
- Dual-source retrieval (catalog + historical returns) improved grounded reasoning.

What did not work well:

- Some low-risk items were over-classified as MEDIUM due to conservative context interpretation.
- Some cases returned INSUFFICIENT_DATA despite available partial signals.
- Arabic quality judge script exists but requires manually filling test outputs before full batch scoring.

---

# 🧪 5. Evals (IMPORTANT)

Evaluation rubric (10 points per case):

- Correctness (risk level alignment): 3
- Grounding and intervention logic: 2
- JSON validity / schema pass: 2
- Multilingual quality (Arabic present/non-empty): 1
- Confidence/refusal behavior: 2

Current recorded run:

- Dataset: 12 cases total
- Pass: 9/12
- Aggregate score: 95/120 (79.2%)

Below are 10 representative test cases (normal + edge + failure) in Input → Expected → Output → Result format:

1. TC-01 Car seat, vehicle unknown
- Input: car seat, child 8 months, no vehicle model
- Expected: HIGH (or at minimum not LOW)
- Output: MEDIUM, compatibility-risk reason, intervention present
- Result: PASS (7/10), but severity under-called vs expected HIGH

2. TC-02 Baby blanket low-risk item
- Input: muslin blanket, child 3 months
- Expected: LOW
- Output: MEDIUM
- Result: PASS (7/10), false-positive risk inflation

3. TC-03 Toy age mismatch
- Input: age 3+ toy for 14-month child
- Expected: HIGH
- Output: MEDIUM
- Result: PASS (7/10), correct mismatch signal but conservative severity

4. TC-04 Formula with dairy allergy
- Input: cow-milk formula + dairy allergy profile
- Expected: HIGH
- Output: HIGH with intervention
- Result: PASS (10/10)

5. TC-05 Formula without allergy
- Input: same formula, no allergies
- Expected: LOW
- Output: LOW
- Result: PASS (10/10)

6. TC-06 Unknown SKU
- Input: UNKNOWN product id
- Expected: INSUFFICIENT_DATA + refusal behavior
- Output: INSUFFICIENT_DATA, refuses_if_no_data=true
- Result: PASS (10/10)

7. TC-07 Arabic preference
- Input: car seat context, language=ar
- Expected: HIGH and valid Arabic
- Output: MEDIUM with Arabic rationale/intervention
- Result: PASS (7/10), Arabic present, severity conservative

8. TC-08 Cart compatibility edge case
- Input: car seat with stroller already in cart
- Expected: MEDIUM
- Output: INSUFFICIENT_DATA
- Result: FAIL (6/10), missed cross-product compatibility signal

9. TC-09 Prompt injection adversarial title
- Input: title attempts to force LOW output
- Expected: not LOW
- Output: INSUFFICIENT_DATA
- Result: PASS (9/10), injection resisted but confidence calibration could improve

10. TC-10 Framing pressure adversarial title
- Input: "ZERO RETURNS EVER" style claim
- Expected: not LOW
- Output: MEDIUM
- Result: PASS (10/10), framing resisted and grounded

Known failures from run:

- TC-08, TC-11, TC-12 did not meet pass threshold.
- Dominant failure pattern: overuse of INSUFFICIENT_DATA and confidence overstatement in ambiguous contexts.

---

# ⚠️ 6. Uncertainty Handling

The system handles uncertainty explicitly instead of forcing confident answers:

- MEDIUM risk is used when mismatch signals are plausible but incomplete (for example: missing vehicle model for a car seat requiring installation constraints).
- INSUFFICIENT_DATA is returned when retrieved or graded context cannot support a grounded decision.
- Refusal path:
  - For unknown/unsupported products, the output sets refusal semantics and avoids fabricated advice.
- Hallucination controls:
  - Prompt rule: use only retrieved context.
  - Relevance grading filters noisy chunks.
  - Strict JSON schema validation rejects malformed or logically inconsistent outputs.
  - Retry-on-parse-failure and failure logging prevent silent corruption.

---

# ⚖️ 7. Tradeoffs

Why this problem:

- Baby product returns are expensive, operationally painful, and often preventable with better contextual guidance.

Why RAG vs pure prompting:

- Return-risk decisions require product-specific constraints and historical return patterns.
- Pure prompting without retrieval is more likely to hallucinate or generalize incorrectly.

Why these models:

- Needed strong reasoning + strict JSON behavior at low cost through OpenRouter.
- Fallback support improved reliability under free-tier volatility.

What was not built (time constraints):

- Real-time catalog sync from production systems
- User profile learning loop from actual outcomes
- Multi-turn clarification dialog before final risk decision
- Robust observability dashboards and alerting

What to improve next:

- Better confidence calibration and uncertainty thresholds
- Stronger cart-level compatibility retrieval
- Harder multilingual evaluation with native human review

---

# 📊 8. Example Outputs

Car seat example:

```json
{
  "product_id": "CAT-001",
  "risk_level": "MEDIUM",
  "risk_score": 0.55,
  "risk_reason_en": "The seat requires a top tether anchor and sufficient headrest clearance, but vehicle information is missing.",
  "risk_reason_ar": "المقعد يتطلب نقطة تثبيت للحزام العلوي ومسافة كافية خلف مسند الرأس، لكن معلومات السيارة غير متوفرة.",
  "intervention_en": "Ask the shopper to confirm vehicle compatibility before purchase.",
  "intervention_ar": "اطلب من المتسوق تأكيد توافق السيارة قبل الشراء.",
  "confidence": 0.78,
  "evidence_sources": ["SRC 1"],
  "refuses_if_no_data": false,
  "language": "en"
}
```

Formula example:

```json
{
  "product_id": "CAT-010",
  "risk_level": "HIGH",
  "risk_score": 0.86,
  "risk_reason_en": "This is cow-milk formula and conflicts with the user’s dairy allergy profile.",
  "risk_reason_ar": "هذه تركيبة تعتمد على حليب البقر وتتعارض مع حساسية الألبان لدى المستخدم.",
  "intervention_en": "Block checkout and suggest hypoallergenic alternatives.",
  "intervention_ar": "أوقف الشراء واقترح بدائل مضادة للحساسية.",
  "confidence": 0.92,
  "evidence_sources": ["SRC 1", "SRC 2"],
  "refuses_if_no_data": false,
  "language": "en"
}
```

Edge case example (unknown SKU):

```json
{
  "product_id": "UNKNOWN-999",
  "risk_level": "INSUFFICIENT_DATA",
  "risk_score": 0.0,
  "risk_reason_en": "No relevant product compatibility or safety data found in retrieved context.",
  "risk_reason_ar": "لا توجد بيانات كافية عن توافق المنتج أو سلامته في السياق المسترجع.",
  "intervention_en": null,
  "intervention_ar": null,
  "confidence": 0.0,
  "evidence_sources": [],
  "refuses_if_no_data": true,
  "language": "en"
}
```

---

# 🎨 9. UI / Demo

The Streamlit frontend is designed as a decision-support panel for checkout teams and mothers:

- Product panel:
  - product title (EN/AR), category, brand, age range, price
- Context controls:
  - child age, vehicle model, allergy toggle, language preference
- Risk output panel:
  - risk level badge (LOW/MEDIUM/HIGH/INSUFFICIENT_DATA)
  - risk score and confidence metrics
  - reason (English + Arabic)
  - suggested intervention (English + Arabic)
  - evidence source list and raw JSON inspector

This keeps the model output transparent and auditable, rather than a black-box score.

---

# 🧱 10. Limitations

- Output quality depends directly on catalog and returns-KB data quality and coverage.
- Model behavior can vary across runs due to provider/model-side variability.
- Current eval dataset is still limited in breadth and long-tail scenarios.
- Some classifications are conservative, causing false MEDIUM or INSUFFICIENT_DATA outcomes.
- Arabic quality evaluation workflow is present but not fully automated end-to-end yet.

---

# 🚀 11. Future Work

- Personalization:
  - use richer user profiles (purchase history, past returns, preference patterns)
- Stronger evals:
  - larger benchmark set with tougher adversarial and multilingual cases
- Real-time product data:
  - live sync with catalog, stock, and compatibility updates
- Fine-tuning:
  - tune scoring/calibration and intervention style on domain-specific return outcomes
- Reliability:
  - add tracing, model-level analytics, and automated regression eval in CI

---

# ⏱️ 12. Time Log (REQUIRED)

- 1.0h: Problem framing, scope definition, and architecture design
- 1.5h: Data shaping and ChromaDB indexing pipeline
- 1.5h: Backend pipeline (retrieve → grade → reason → validate)
- 1.0h: Streamlit frontend and API integration
- 1.0h: Evaluation harness + adversarial tests
- 0.5h: Debugging, schema hardening, and fallback policy tuning

Total: 6.5 hours

---

# 🧠 13. AI Usage Note (REQUIRED)

## Where did I use AI

AI was used selectively, primarily to validate design decisions and accelerate implementation. The core system architecture (RAG pipeline, grading → reasoning flow, fallback strategy), risk logic, and evaluation design were built independently. AI was mainly used to pressure-test edge cases and refine prompt behavior.

## What prompts/tools did I use

- Used OpenRouter for model access (GPT-OSS-120B, Nemotron).
- Used conversational prompting (via ChatGPT / Copilot) to:
  - iterate on reasoning and grading prompts
  - debug failure cases (invalid JSON, missing context usage)
  - explore tradeoffs in model selection and fallback handling

## What outputs did I accept or reject

### ✅ Accepted

- Suggestions to enforce strict JSON output, which significantly improved system reliability.
- Help in designing fallback logic (handling 429/504 errors) to make the system robust.
- Prompt refinements that improved multilingual clarity (EN + AR).
- Guidance for structuring evidence extraction, replacing placeholder references with real grounded snippets.

### ❌ Rejected / Modified

- Generic or overly verbose reasoning outputs were replaced with structured, concise explanations.
- Model suggestions that were unstable or unavailable (invalid OpenRouter models) were replaced with working alternatives.
- Grading logic that defaulted to rejecting all chunks was modified to avoid pipeline collapse.
- Suggestions that treated this as a pure LLM problem were adjusted to reinforce structured constraints and rule-guided reasoning.
