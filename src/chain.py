import json
import logging
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI  # OpenRouter uses OpenAI-compatible client

from src.schema import QueryContext, ReturnRiskOutput, ValidationFailure, RiskLevel
from src.retriever import retrieve, RetrievalResult, RetrievedChunk

logger = logging.getLogger(__name__)

# Load prompts from files
SYSTEM_PROMPT = Path("prompts/system_reasoning.txt").read_text()
GRADING_PROMPT_TEMPLATE = Path("prompts/grading.txt").read_text()

# Confidence ceiling when context is thin
THIN_CONTEXT_CONFIDENCE_CAP = 0.6


def grade_chunks(
    chunks: list[RetrievedChunk],
    query_context: QueryContext,
    openrouter_client: OpenAI,
) -> list[RetrievedChunk]:
    """
    Use a fast/cheap model to filter irrelevant chunks before the main call.
    Returns only chunks graded as relevant.
    """
    relevant_chunks = []
    
    query_summary = (
        f"Category: {query_context.category}, "
        f"Child age: {query_context.child_age_months} months, "
        f"Vehicle: {query_context.vehicle_model or 'not specified'}"
    )
    
    for chunk in chunks:
        prompt = GRADING_PROMPT_TEMPLATE.format(
            query_context=query_summary,
            chunk_text=chunk.text
        )
        
        try:
            # ✅ CHANGED: use OpenRouter client for grading call
            response = openrouter_client.chat.completions.create(
                model="meta-llama/llama-3.1-8b-instruct:free",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=100
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown backticks if present
            raw = raw.replace("```json", "").replace("```", "").strip()
            result = json.loads(raw)
            if result.get("relevant"):
                relevant_chunks.append(chunk)
        except Exception as e:
            # On grading failure, keep the chunk (false negative is better than false positive drop)
            logger.warning(f"Grading failed for chunk {chunk.id}: {e}")
            relevant_chunks.append(chunk)
    
    return relevant_chunks


def format_chunks_for_prompt(chunks: list[RetrievedChunk]) -> str:
    """
    Format retrieved chunks into a clean context block for the LLM.
    """
    formatted = []
    for i, chunk in enumerate(chunks):
        formatted.append(
            f"[SOURCE {i+1}: {chunk.id} | {chunk.source} | sim={chunk.similarity}]\n{chunk.text}"
        )
    return "\n\n---\n\n".join(formatted)


def call_reasoning_llm(
    context: QueryContext,
    chunks: list[RetrievedChunk],
    openrouter_client: OpenAI,  # ✅ CHANGED: use OpenRouter client
    confidence_cap: Optional[float] = None,
) -> dict:
    """
    Main LLM call. Returns raw dict from LLM (not yet validated by Pydantic).
    Uses OpenRouter (OpenAI-compatible) client only.
    """
    user_prompt = f"""
Product being assessed: {context.product_id}
Title (EN): {context.product_title_en}
Title (AR): {context.product_title_ar or 'not available'}
Category: {context.category}
Brand: {context.brand or 'not specified'}
Child age: {context.child_age_months or 'not specified'} months
Vehicle: {context.vehicle_model or 'not specified'}
Cart also contains: {', '.join(context.cart_contents) if context.cart_contents else 'nothing else'}
Known allergies: {', '.join(context.has_allergies) if context.has_allergies else 'none recorded'}
User language preference: {context.language_preference}

RETRIEVED CONTEXT:
{format_chunks_for_prompt(chunks)}

Assess return risk and return JSON.
{"NOTE: Context is limited. Cap your confidence at " + str(confidence_cap) + " maximum." if confidence_cap else ""}
    """.strip()

    # ✅ CHANGED: call OpenRouter via openrouter_client
    response = openrouter_client.chat.completions.create(
        model="meta-llama/llama-3.3-70b-instruct:free",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT + "\nReturn strictly valid JSON. No explanation. No markdown."
            },
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1,
        max_tokens=1000
    )

    raw_text = response.choices[0].message.content.strip()
    # ✅ CHANGED: JSON cleaning for backticks
    if raw_text.startswith("```"):
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()

    return json.loads(raw_text), raw_text


def analyze_return_risk(
    context: QueryContext,
    openrouter_client: OpenAI,  # ✅ CHANGED: remove anthropic client, use openrouter only
) -> tuple[Optional[ReturnRiskOutput], Optional[ValidationFailure]]:
    """
    Full pipeline: retrieve → grade → reason → validate.
    Returns (output, None) on success or (None, failure) on failure.
    """
    
    # Stage 1: Retrieve
    retrieval = retrieve(context)
    
    if retrieval.status == "INSUFFICIENT_DATA":
        # No relevant context — return a well-formed INSUFFICIENT_DATA response
        output = ReturnRiskOutput(
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
            language=context.language_preference
        )
        return output, None
    
    # Stage 2: Grade chunks
    relevant_chunks = grade_chunks(retrieval.chunks, context, openrouter_client)
    
    if not relevant_chunks:
        # Grading removed everything — treat as insufficient
        output = ReturnRiskOutput(
            product_id=context.product_id,
            risk_level=RiskLevel.INSUFFICIENT_DATA,
            risk_score=0.0,
            risk_reason_en="Retrieved context was not relevant to this specific product and user context.",
            risk_reason_ar="لم يكن السياق المسترجع ذا صلة بهذا المنتج وسياق المستخدم.",
            intervention_en=None,
            intervention_ar=None,
            confidence=0.0,
            evidence_sources=[],
            refuses_if_no_data=True,
            language=context.language_preference
        )
        return output, None
    
    # Determine confidence cap based on context richness
    confidence_cap = None
    if len(relevant_chunks) <= 2:
        confidence_cap = THIN_CONTEXT_CONFIDENCE_CAP
    
    # Stage 3: Reason
    try:
        raw_dict, raw_text = call_reasoning_llm(
            context, relevant_chunks, openrouter_client, confidence_cap
        )
    except json.JSONDecodeError as e:
        failure = ValidationFailure(
            product_id=context.product_id,
            error_type="json_parse_error",
            error_detail=str(e),
            raw_llm_output="(non-JSON response)"
        )
        return None, failure
    
    # Stage 4: Validate
    raw_dict["product_id"] = context.product_id
    raw_dict["language"] = context.language_preference
    
    try:
        output = ReturnRiskOutput(**raw_dict)
        # Apply confidence cap post-validation
        if confidence_cap and output.confidence > confidence_cap:
            output = output.model_copy(update={"confidence": confidence_cap})
        return output, None
    except Exception as e:
        failure = ValidationFailure(
            product_id=context.product_id,
            error_type="schema_validation_error",
            error_detail=str(e),
            raw_llm_output=json.dumps(raw_dict)
        )
        # Retry once with error context using OpenRouter
        return _retry_with_error(context, relevant_chunks, raw_dict, str(e), 
                      openrouter_client, confidence_cap)


def _retry_with_error(
    context: QueryContext,
    chunks: list[RetrievedChunk],
    failed_dict: dict,
    error_msg: str,
    openrouter_client: OpenAI,  # ✅ CHANGED: use OpenRouter client
    confidence_cap: Optional[float]
) -> tuple[Optional[ReturnRiskOutput], Optional[ValidationFailure]]:
    """
    Self-correcting retry: append the validation error to the prompt.
    This catches ~80% of transient formatting failures.
    """
    correction_prompt = f"""
Your previous response failed validation with this error:
{error_msg}

Your previous response was:
{json.dumps(failed_dict, indent=2)}

Please fix the issue and return corrected JSON only.
    """
    
    try:
        # ✅ CHANGED: retry via OpenRouter with the instructed model
        response = openrouter_client.chat.completions.create(
            model="meta-llama/llama-3.3-70b-instruct:free",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT + "\nReturn strictly valid JSON. No explanation. No markdown."},
                {"role": "user", "content": format_chunks_for_prompt(chunks)},
                {"role": "user", "content": json.dumps(failed_dict)},
                {"role": "user", "content": correction_prompt}
            ],
            temperature=0.1,
            max_tokens=1000
        )

        raw_text = response.choices[0].message.content.strip()
        # ✅ CHANGED: JSON cleaning for backticks
        if raw_text.startswith("```"):
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()

        corrected = json.loads(raw_text)
        corrected["product_id"] = context.product_id
        output = ReturnRiskOutput(**corrected)
        return output, None
    except Exception as e:
        failure = ValidationFailure(
            product_id=context.product_id,
            error_type="retry_failed",
            error_detail=str(e),
            raw_llm_output=str(failed_dict)
        )
        return None, failure