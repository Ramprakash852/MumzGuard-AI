import json
import logging
import time
from pathlib import Path
from typing import List, Optional, Tuple

from openai import OpenAI

from src.schema import (
    QueryContext,
    ReturnRiskOutput,
    ValidationFailure,
    RiskLevel,
)
from src.retriever import retrieve, RetrievedChunk

logger = logging.getLogger(__name__)

# Models (per user request)
GRADING_MODEL = "liquidai/lfm2.5-1.2b-thinking:free"
REASONING_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "nvidia/nemotron-3-super:free",
]

# Prompts
SYSTEM_PROMPT = Path("prompts/system_reasoning.txt").read_text() if Path("prompts/system_reasoning.txt").exists() else ""

# Confidence cap when context is thin
THIN_CONTEXT_CONFIDENCE_CAP = 0.6


def _clean_llm_output(raw: str) -> str:
    if not isinstance(raw, str):
        raw = str(raw)
    return raw.replace("```json", "").replace("```", "").strip()


def _get_status_code_from_exc(exc: Exception) -> Optional[int]:
    # Best-effort extraction of HTTP-like status codes from exceptions
    for attr in ("http_status", "status_code", "status"):
        code = getattr(exc, attr, None)
        if isinstance(code, int):
            return code

    # Fallback: try to find numeric codes in the string
    try:
        s = str(exc)
        for token in ("429", "504", "404"):
            if token in s:
                return int(token)
    except Exception:
        pass
    return None


def grade_chunks(
    chunks: List[RetrievedChunk],
    context: QueryContext,
    client: OpenAI,
) -> List[RetrievedChunk]:
    """
    Use a fast classifier model to keep only relevant chunks.
    If parsing fails for a chunk, default to relevant=False.
    """
    kept: List[RetrievedChunk] = []

    prompt_template = (
        "You are a strict relevance classifier.\n"
        "Return ONLY JSON in the exact format: {\"relevant\": true|false}.\n"
        "No explanation, no extra keys, no markdown.\n"
        "Input: {context_summary}\n"
        "Chunk: {chunk_text}\n"
    )

    context_summary = (
        f"product_id={context.product_id}; category={context.category}; "
        f"child_age_months={context.child_age_months}; vehicle={context.vehicle_model or 'N/A'}"
    )

    for chunk in chunks:
        prompt = prompt_template.replace("{context_summary}", context_summary).replace(
            "{chunk_text}", chunk.text
        )

        try:
            resp = client.chat.completions.create(
                model=GRADING_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=32,
            )
            raw = _clean_llm_output(resp.choices[0].message.content)
            try:
                parsed = json.loads(raw)
                relevant = bool(parsed.get("relevant", False))
            except Exception:
                logger.debug("Failed to parse grading JSON, defaulting relevant=False")
                relevant = False
        except Exception as e:
            logger.warning(f"Grading API call failed for chunk {chunk.id}: {e}")
            relevant = False

        if relevant:
            kept.append(chunk)

    return kept


def format_chunks_for_prompt(chunks: List[RetrievedChunk]) -> str:
    pieces = []
    for i, c in enumerate(chunks, start=1):
        pieces.append(f"[SRC {i} | {c.source} | sim={c.similarity:.3f}]\n{c.text}")
    return "\n\n---\n\n".join(pieces)


def call_llm_with_fallback(client: OpenAI, messages: List[dict]) -> Tuple[Optional[str], Optional[dict]]:
    """
    Try each model in REASONING_MODELS with the prescribed retry/backoff policy.

    Returns (raw_text, metadata) on success or (None, error_obj) on total failure.
    """
    backoffs = [2, 4, 6]

    for model in REASONING_MODELS:
        logger.debug(f"Trying reasoning model: {model}")
        for attempt in range(1, 4):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=1024,
                )
                raw = resp.choices[0].message.content
                raw = _clean_llm_output(raw)
                return raw, {"model": model}

            except Exception as e:
                code = _get_status_code_from_exc(e)
                logger.warning(f"Model {model} attempt {attempt} failed (code={code}): {e}")

                # Immediate model-skip rules
                if code in (429, 404, 504):
                    logger.info(f"Skipping model {model} due to status {code}")
                    break  # go to next model

                # Retry with backoff for other errors
                if attempt < 3:
                    sleep_for = backoffs[attempt - 1]
                    logger.debug(f"Retrying model {model} after {sleep_for}s")
                    time.sleep(sleep_for)
                    continue
                else:
                    logger.info(f"Exhausted retries for model {model}, moving to next model")
                    break

    return None, {"error": "llm_unavailable", "message": "All models failed"}


def analyze_return_risk(
    context: QueryContext,
    client: OpenAI,
) -> Tuple[Optional[ReturnRiskOutput], Optional[ValidationFailure]]:
    """
    Full pipeline: retrieve → grade → reason (with fallback) → validate.

    Returns (ReturnRiskOutput, None) on success or (None, ValidationFailure) on failure.
    """
    # 1) Retrieve
    retrieval = retrieve(context)

    if retrieval.status == "INSUFFICIENT_DATA":
        out = ReturnRiskOutput(
            product_id=context.product_id,
            risk_level=RiskLevel.INSUFFICIENT_DATA,
            risk_score=0.0,
            risk_reason_en="Insufficient product data in knowledge base to assess return risk.",
            risk_reason_ar="لا تتوفر بيانات كافية في قاعدة المعرفة لتقييم مخاطر الإرجاع.",
            intervention_en=None,
            intervention_ar=None,
            confidence=0.0,
            evidence_sources=[],
            refuses_if_no_data=True,
            language=context.language_preference,
        )
        return out, None

    # 2) Grade
    relevant_chunks = grade_chunks(retrieval.chunks, context, client)

    if not relevant_chunks:
        out = ReturnRiskOutput(
            product_id=context.product_id,
            risk_level=RiskLevel.INSUFFICIENT_DATA,
            risk_score=0.0,
            risk_reason_en="Retrieved context was not relevant to this product and user context.",
            risk_reason_ar="لم يكن السياق المسترجع ذا صلة بهذا المنتج وسياق المستخدم.",
            intervention_en=None,
            intervention_ar=None,
            confidence=0.0,
            evidence_sources=[],
            refuses_if_no_data=True,
            language=context.language_preference,
        )
        return out, None

    # confidence cap
    confidence_cap = None
    if len(relevant_chunks) <= 2:
        confidence_cap = THIN_CONTEXT_CONFIDENCE_CAP

    # 3) Reasoning: build messages
    system = SYSTEM_PROMPT + "\nReturn strictly valid JSON. No explanation. No markdown."
    user_text = (
        f"Product: {context.product_id}\n"
        f"Title EN: {context.product_title_en}\n"
        f"Title AR: {context.product_title_ar or 'N/A'}\n"
        f"Category: {context.category}\n"
        f"Brand: {context.brand or 'N/A'}\n"
        f"Child age months: {context.child_age_months or 'N/A'}\n"
        f"Vehicle: {context.vehicle_model or 'N/A'}\n"
        f"Cart: {', '.join(context.cart_contents) if context.cart_contents else 'none'}\n"
        f"Allergies: {', '.join(context.has_allergies) if context.has_allergies else 'none'}\n\n"
        f"RETRIEVED:\n{format_chunks_for_prompt(relevant_chunks)}\n\n"
        f"ASSESS return risk and return strictly valid JSON."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]

    raw, meta = call_llm_with_fallback(client, messages)
    if raw is None:
        # All models failed — return fail-safe error as ValidationFailure for upstream logging
        vf = ValidationFailure(
            product_id=context.product_id,
            error_type="llm_unavailable",
            error_detail=meta.get("message", "All models failed"),
            raw_llm_output="",
        )
        return None, vf

    # 4) Clean
    cleaned = _clean_llm_output(raw)

    # 5) Validate JSON (retry once on parse failure)
    parsed = None
    try:
        parsed = json.loads(cleaned)
    except Exception as e:
        logger.warning(f"Initial JSON parse failed: {e}; retrying once")
        # Retry once: ask the LLM to return strictly JSON only
        retry_messages = messages + [
            {"role": "system", "content": "Return strictly valid JSON only. No explanation."}
        ]
        raw2, meta2 = call_llm_with_fallback(client, retry_messages)
        if raw2 is None:
            vf = ValidationFailure(
                product_id=context.product_id,
                error_type="llm_unavailable",
                error_detail=meta2.get("message", "All models failed on retry"),
                raw_llm_output="",
            )
            return None, vf

        cleaned2 = _clean_llm_output(raw2)
        try:
            parsed = json.loads(cleaned2)
        except Exception as e2:
            vf = ValidationFailure(
                product_id=context.product_id,
                error_type="json_parse_error",
                error_detail=str(e2),
                raw_llm_output=cleaned2,
            )
            return None, vf

    # 6) Normalize & validate with Pydantic
    parsed["product_id"] = context.product_id
    parsed["language"] = context.language_preference

    try:
        output = ReturnRiskOutput(**parsed)
        # Apply confidence cap if needed
        if confidence_cap and output.confidence > confidence_cap:
            output = output.model_copy(update={"confidence": confidence_cap})
        return output, None
    except Exception as e:
        vf = ValidationFailure(
            product_id=context.product_id,
            error_type="schema_validation_error",
            error_detail=str(e),
            raw_llm_output=json.dumps(parsed),
        )
        return None, vf
