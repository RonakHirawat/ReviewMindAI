import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import (
    Base,
    RawReview,
    ReviewClean,
    Theme,
    ReviewAspect,
    ThemeSentimentWindow,
    ProductCatalog,
    QueryLog
)

@pytest.fixture
def db_session():
    # In-memory SQLite database
    engine = create_engine("sqlite:///:memory:")
    # Create all tables
    Base.metadata.create_all(engine)
    # Session factory
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)

def test_insert_and_retrieve_all_tables(db_session):
    now = datetime.utcnow()
    
    # 1. Insert ProductCatalog
    product = ProductCatalog(
        product_id="FAN-TBL-001",
        sku="FT-001-BLK",
        name="AeroBreeze 400",
        category="fan",
        sub_category="table fan",
        launch_date=now,
        status="active"
    )
    db_session.add(product)
    
    # 2. Insert RawReview
    raw_rev = RawReview(
        review_id="raw-1",
        source_platform="amazon",
        source_review_id="amazon-raw-1",
        product_id="FAN-TBL-001",
        raw_payload={"rating": 4, "text": "Good fan speed but a bit loud"},
        ingested_at=now,
        content_hash="hash123",
        fetch_batch_id="batch-abc"
    )
    db_session.add(raw_rev)
    
    # 3. Insert ReviewClean
    clean_rev = ReviewClean(
        review_id="clean-1",
        product_id="FAN-TBL-001",
        text_clean="Good fan speed but a bit loud",
        text_original="Good fan speed but a bit loud",
        language="en",
        star_rating=4,
        review_date=now,
        source_platform="amazon",
        is_spam=False,
        spam_score=0.1,
        bot_score=0.05,
        trust_score=0.95,
        injection_flag=False,
        quarantine_reason=None,
        dedupe_group_id=None,
        pii_redacted_at=None,
        preprocess_version="v1.0"
    )
    db_session.add(clean_rev)
    
    # Commit clean_rev first because review_aspects has a foreign key referencing it
    db_session.commit()
    
    # 4. Insert Theme
    theme = Theme(
        theme_id="theme-noise",
        taxonomy_version="v1",
        canonical_label="Noise Level",
        definition="Reviews complaining about or praising sound levels",
        scope_category="operational",
        status="active",
        parent_theme_id=None,
        merged_into=None,
        valid_from=now,
        valid_to=None,
        created_by="admin",
        cohesion_score=0.85,
        member_count=10
    )
    db_session.add(theme)
    
    # 5. Insert ReviewAspect
    aspect = ReviewAspect(
        review_id="clean-1",
        product_id="FAN-TBL-001",
        theme_id="theme-noise",
        taxonomy_version="v1",
        aspect_phrase_raw="a bit loud",
        polarity=-0.3,
        intensity=0.5,
        verbatim_span="a bit loud",
        span_validated=True,
        confidence=0.95,
        extraction_model_version="claude-3-haiku",
        prompt_version="v1.2",
        extracted_at=now
    )
    db_session.add(aspect)
    
    # 6. Insert ThemeSentimentWindow
    window = ThemeSentimentWindow(
        theme_id="theme-noise",
        taxonomy_version="v1",
        product_id="FAN-TBL-001",
        window_end=now,
        window_days=30,
        source_platform="amazon",
        language="en",
        n_reviews=100,
        n_mentions=20,
        mention_rate=0.20,
        ci_low=0.15,
        ci_high=0.25,
        mean_polarity=-0.4,
        pct_negative=0.75,
        delta_vs_prev=-0.05,
        p_value=0.02,
        p_value_adj=0.05,
        effect_size=0.3,
        is_significant=True,
        support_class="medium",
        extraction_model_version="claude-3-haiku",
        computed_at=now
    )
    db_session.add(window)
    
    # 7. Insert QueryLog
    query_log = QueryLog(
        query_id="query-uuid-123",
        question="Is the fan quiet?",
        query_plan={"steps": ["search", "aggregate"]},
        resolved_scope={"products": ["FAN-TBL-001"]},
        evidence_refs=[],
        verifier_verdicts={},
        answer="Yes, mostly quiet.",
        confidence=0.9,
        abstained=False,
        prompt_version="q-v1",
        model_versions={"qa": "claude-3-sonnet"},
        latency_ms=1200,
        token_cost=0.002,
        created_at=now
    )
    db_session.add(query_log)
    
    db_session.commit()
    
    # --- Retrievals & Validations ---
    
    # 1. ProductCatalog validation
    retrieved_product = db_session.query(ProductCatalog).filter_by(product_id="FAN-TBL-001").first()
    assert retrieved_product is not None
    assert retrieved_product.sku == "FT-001-BLK"
    assert retrieved_product.name == "AeroBreeze 400"
    
    # 2. RawReview validation
    retrieved_raw = db_session.query(RawReview).filter_by(review_id="raw-1").first()
    assert retrieved_raw is not None
    assert retrieved_raw.source_platform == "amazon"
    assert retrieved_raw.raw_payload["rating"] == 4
    
    # 3. ReviewClean validation
    retrieved_clean = db_session.query(ReviewClean).filter_by(review_id="clean-1").first()
    assert retrieved_clean is not None
    assert retrieved_clean.star_rating == 4
    assert retrieved_clean.text_clean == "Good fan speed but a bit loud"
    
    # 4. Theme validation
    retrieved_theme = db_session.query(Theme).filter_by(theme_id="theme-noise").first()
    assert retrieved_theme is not None
    assert retrieved_theme.canonical_label == "Noise Level"
    
    # 5. ReviewAspect validation
    retrieved_aspect = db_session.query(ReviewAspect).filter_by(review_id="clean-1").first()
    assert retrieved_aspect is not None
    assert retrieved_aspect.aspect_phrase_raw == "a bit loud"
    assert retrieved_aspect.polarity == -0.3
    
    # 6. ThemeSentimentWindow validation
    retrieved_window = db_session.query(ThemeSentimentWindow).filter_by(
        theme_id="theme-noise",
        product_id="FAN-TBL-001",
        source_platform="amazon"
    ).first()
    assert retrieved_window is not None
    assert retrieved_window.n_reviews == 100
    assert retrieved_window.is_significant is True
    
    # 7. QueryLog validation
    retrieved_query = db_session.query(QueryLog).filter_by(query_id="query-uuid-123").first()
    assert retrieved_query is not None
    assert retrieved_query.question == "Is the fan quiet?"
    assert retrieved_query.query_plan["steps"] == ["search", "aggregate"]
