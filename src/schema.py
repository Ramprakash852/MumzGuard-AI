from pydantic import BaseModel, field_validator, model_validator
from enum import Enum
from typing import Optional
from datetime import datetime


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ReturnRiskOutput(BaseModel):
    product_id: str
    risk_level: RiskLevel
    risk_score: float                    # 0.0–1.0, maps to risk_level
    risk_reason_en: str                  # Grounded in retrieved context
    risk_reason_ar: str                  # Native Arabic, not translation
    intervention_en: Optional[str]       # Null if LOW
    intervention_ar: Optional[str]       # Null if LOW
    confidence: float                    # 0.0–1.0, LLM self-reported
    evidence_sources: list[str]          # Which chunks drove the decision
    refuses_if_no_data: bool = False
    language: str = "en"

    @field_validator('confidence', 'risk_score')
    @classmethod
    def score_in_range(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Score must be 0.0–1.0, got {v}")
        return round(v, 2)

    @field_validator('risk_reason_ar')
    @classmethod
    def arabic_non_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Arabic reason cannot be empty")
        # Basic check: Arabic Unicode range
        arabic_chars = sum(1 for c in v if '\u0600' <= c <= '\u06FF')
        if arabic_chars < 3:
            raise ValueError("Arabic reason must contain Arabic characters")
        return v

    @model_validator(mode='after')
    def intervention_required_for_high_risk(self):
        if self.risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM):
            if not self.intervention_en or not self.intervention_ar:
                raise ValueError(
                    f"intervention_en and intervention_ar required when risk_level is {self.risk_level}"
                )
        return self

    @model_validator(mode='after')
    def risk_score_aligned_with_level(self):
        if self.risk_level == RiskLevel.INSUFFICIENT_DATA:
            if self.risk_score != 0.0:
                raise ValueError("risk_score must be 0.0 when risk_level is INSUFFICIENT_DATA")
            return self

        if self.risk_level == RiskLevel.LOW and not (0.0 <= self.risk_score <= 0.39):
            raise ValueError("risk_score must be in 0.0-0.39 when risk_level is LOW")

        if self.risk_level == RiskLevel.MEDIUM and not (0.4 <= self.risk_score <= 0.69):
            raise ValueError("risk_score must be in 0.4-0.69 when risk_level is MEDIUM")

        if self.risk_level == RiskLevel.HIGH and not (0.7 <= self.risk_score <= 1.0):
            raise ValueError("risk_score must be in 0.7-1.0 when risk_level is HIGH")

        return self


class ValidationFailure(BaseModel):
    product_id: str
    error_type: str
    error_detail: str
    raw_llm_output: str
    timestamp: str = datetime.utcnow().isoformat()


class QueryContext(BaseModel):
    product_id: str
    product_title_en: str
    product_title_ar: Optional[str]
    category: str
    brand: Optional[str]
    child_age_months: Optional[int]
    vehicle_model: Optional[str]
    cart_contents: list[str] = []
    has_allergies: list[str] = []
    language_preference: str = "en"