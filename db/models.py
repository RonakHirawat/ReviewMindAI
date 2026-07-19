from datetime import datetime, date
from typing import Any, Dict, List, Optional
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Date, Text, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class RawReview(Base):
    __tablename__ = "raw_reviews"

    review_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    source_platform: Mapped[str] = mapped_column(String(50))
    source_review_id: Mapped[str] = mapped_column(String(100))
    product_id: Mapped[str] = mapped_column(String(50))
    raw_payload: Mapped[Dict[str, Any]] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    content_hash: Mapped[str] = mapped_column(String(64))
    fetch_batch_id: Mapped[str] = mapped_column(String(50))

class ReviewClean(Base):
    __tablename__ = "reviews_clean"

    review_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(50))
    text_clean: Mapped[str] = mapped_column(Text)
    text_original: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10))
    star_rating: Mapped[int] = mapped_column(Integer)
    review_date: Mapped[datetime] = mapped_column(DateTime)
    source_platform: Mapped[str] = mapped_column(String(50))
    is_spam: Mapped[bool] = mapped_column(Boolean, default=False)
    spam_score: Mapped[float] = mapped_column(Float)
    bot_score: Mapped[float] = mapped_column(Float)
    trust_score: Mapped[float] = mapped_column(Float)
    injection_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    quarantine_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dedupe_group_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    pii_redacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    product_ambiguous: Mapped[Optional[bool]] = mapped_column(Boolean, default=False, nullable=True)
    preprocess_version: Mapped[str] = mapped_column(String(20))


class Theme(Base):
    __tablename__ = "themes"

    theme_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    taxonomy_version: Mapped[str] = mapped_column(String(20))
    canonical_label: Mapped[str] = mapped_column(String(100))
    definition: Mapped[str] = mapped_column(Text)
    scope_category: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20)) # e.g. active, deprecated
    parent_theme_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    merged_into: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(50))
    cohesion_score: Mapped[float] = mapped_column(Float)
    member_count: Mapped[int] = mapped_column(Integer)

class ReviewAspect(Base):
    __tablename__ = "review_aspects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[str] = mapped_column(String(50), ForeignKey("reviews_clean.review_id"))
    product_id: Mapped[str] = mapped_column(String(50))
    theme_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    taxonomy_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    aspect_phrase_raw: Mapped[str] = mapped_column(String(255))
    polarity: Mapped[float] = mapped_column(Float)
    intensity: Mapped[float] = mapped_column(Float)
    verbatim_span: Mapped[str] = mapped_column(String(255))
    span_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float)
    extraction_model_version: Mapped[str] = mapped_column(String(50))
    prompt_version: Mapped[str] = mapped_column(String(20))
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ThemeSentimentWindow(Base):
    __tablename__ = "theme_sentiment_window"

    theme_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    taxonomy_version: Mapped[str] = mapped_column(String(20), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    window_end: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    window_days: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_platform: Mapped[str] = mapped_column(String(50), primary_key=True)
    language: Mapped[str] = mapped_column(String(10), primary_key=True)
    
    n_reviews: Mapped[int] = mapped_column(Integer)
    n_mentions: Mapped[int] = mapped_column(Integer)
    mention_rate: Mapped[float] = mapped_column(Float)
    ci_low: Mapped[float] = mapped_column(Float)
    ci_high: Mapped[float] = mapped_column(Float)
    mean_polarity: Mapped[float] = mapped_column(Float)
    pct_negative: Mapped[float] = mapped_column(Float)
    delta_vs_prev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p_value_adj: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    effect_size: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_significant: Mapped[bool] = mapped_column(Boolean)
    support_class: Mapped[str] = mapped_column(String(50))
    extraction_model_version: Mapped[str] = mapped_column(String(50))
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ProductCatalog(Base):
    __tablename__ = "product_catalog"

    product_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    sku: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    sub_category: Mapped[str] = mapped_column(String(50))
    launch_date: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20)) # e.g. active, discontinued

class QueryLog(Base):
    __tablename__ = "query_logs"

    query_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    query_plan: Mapped[Dict[str, Any]] = mapped_column(JSON)
    resolved_scope: Mapped[Dict[str, Any]] = mapped_column(JSON)
    evidence_refs: Mapped[List[Any]] = mapped_column(JSON)
    verifier_verdicts: Mapped[Dict[str, Any]] = mapped_column(JSON)
    answer: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_version: Mapped[str] = mapped_column(String(20))
    model_versions: Mapped[Dict[str, Any]] = mapped_column(JSON)
    latency_ms: Mapped[int] = mapped_column(Integer)
    token_cost: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    review_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    extraction_model_version: Mapped[str] = mapped_column(String(50))
    prompt_version: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20)) # success, failed, retry_success, retry_failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

