# TRADEOFFS.md

## Why return risk

Return risk has an unambiguous success metric: did the system correctly predict a return?
Gift finder success is inherently subjective. Product description quality is hard to
measure objectively at prototype scale. Return risk also has a direct business number
attached (~AED 65 per return in reverse logistics), which makes the ROI case easy to
defend in any review conversation.

## Architecture decisions

**ChromaDB over Pinecone/Qdrant:**
ChromaDB runs entirely locally with no API key and supports metadata filtering, which
is essential for keeping car seat chunks out of formula queries. At 80 indexed documents,
there is no performance reason to run a separate server.

**multilingual-e5-large:**
English-only embedding models silently fail on Arabic queries — distances look plausible
but semantic meaning is not preserved. multilingual-e5-large handles Arabic-English
cross-lingual retrieval and uses instruction prefixes (passage:/query:) that measurably
improve retrieval precision.

**openai/gpt-oss-120b:free (dual-purpose: grading + reasoning):**
GPT-OSS-120B via OpenRouter provides strong structured reasoning and reliable JSON output.
Used for both chunk relevance grading (fast, binary decision) and final risk reasoning (thorough analysis).
Free tier on OpenRouter made it accessible for an internship project while maintaining quality.

**nvidia/nemotron-3-super:free (fallback reasoning):**
Fallback model reduces dependency on a single model provider. If GPT-OSS fails or returns 429/504,
the system immediately tries Nemotron with exponential backoff (2s, 4s, 6s). This dual-model strategy
improved robustness significantly during testing—model availability varies on free tiers.

**OpenRouter abstraction:**
OpenAI-compatible API client abstracts model switching. Single API key, unified error handling, seamless
model fallback. Preferred over direct model APIs for flexibility and cost control.

**Plain Python + Pydantic over LangChain:**
This pipeline has three LLM calls (retrieval → grading → reasoning) with specific error handling,
retry logic, and confidence capping between them. Plain Python with the OpenAI SDK makes each stage
readable and debuggable. Pydantic enforces strict schema validation at the output boundary,
catching malformed JSON and missing fields before they propagate. LangChain would obscure prompt
formatting and validation logic in ways that are harder to inspect and iterate on—critical for
production safety.

## What I cut and why

- **Real-time inventory/price/catalog sync:** No Mumzworld API access during internship. Data is static
  (JSON catalogs). At scale, would need CDC or polling to keep embeddings fresh.
- **Image analysis (product photos):** Would add multimodal complexity without materially improving
  compatibility detection, which is inherently text-based (specs, reviews, safety notes).
- **User conversation history / multi-turn clarification:** Architecture is stateless single-request-response.
  Multi-turn would require session management and would defer final recommendations.
- **Fine-tuning on Arabic embeddings:** No Gulf-region baby product label set available. Using off-the-shelf
  multilingual-e5-large captures 80% of signal; fine-tuning is the correct next step.
- **Real-time confidence calibration:** Confidence is currently LLM self-reported. Empirical calibration
  requires labeled return outcomes, which would come post-launch.

## What I'd build next

1. **Production data integration:** Replace synthetic catalog + returns KB with real Mumzworld product feeds
   and actual return events (anonymized). This immediately removes synthetic data bias.
2. **Confidence calibration:** Train a Platt scaling model using real return outcomes as ground truth.
   Current confidence is LLM self-reported; empirical calibration is the next priority.
3. **Cart-aware retrieval:** Extend retriever to surface compatibility signals between products already in
   cart and the new product (e.g., travel system compatibility). This fixes TC-08 failure pattern.
4. **Cross-lingual embedding fine-tuning:** Fine-tune multilingual-e5-large on Gulf-region baby product
   terminology to close the 10–15% Arabic retrieval recall gap.
5. **WhatsApp + SMS integration:** Stateless architecture allows thin adapter layer. Start with WhatsApp
   Business API for order pre-fulfillment risk checks (before checkout).
6. **Feedback loop:** Log confirmed returns vs. system predictions. Use mismatches to iteratively improve
   retrieval coverage and reasoning prompts.