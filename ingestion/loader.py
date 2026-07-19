import hashlib
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from db.models import RawReview

def compute_content_hash(payload: Dict[str, Any]) -> str:
    # Sort keys for deterministic JSON serialization
    serialized = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

def ingest_reviews(session: Session, reviews_list: List[Dict[str, Any]], batch_id: str = None) -> Dict[str, int]:
    """
    Ingests a list of raw review dictionaries into the raw_reviews table.
    Ensures idempotency by performing an upsert on (source_platform, source_review_id).
    
    Returns a dict with count of inserted and updated rows.
    """
    if not batch_id:
        batch_id = str(uuid.uuid4())
        
    now = datetime.utcnow()
    inserted_count = 0
    updated_count = 0
    
    # Process reviews
    for raw in reviews_list:
        platform = raw.get("source_platform")
        source_rev_id = raw.get("source_review_id")
        product_id = raw.get("product_id")
        review_id = raw.get("review_id") or str(uuid.uuid4())[:18]
        
        if not platform or not source_rev_id:
            # Skip invalid payloads
            continue
            
        content_hash = compute_content_hash(raw)
        
        # Check if row already exists
        existing = session.query(RawReview).filter_by(
            source_platform=platform,
            source_review_id=source_rev_id
        ).first()
        
        if existing:
            # Update fields
            existing.raw_payload = raw
            existing.product_id = product_id
            existing.content_hash = content_hash
            existing.fetch_batch_id = batch_id
            existing.ingested_at = now
            updated_count += 1
        else:
            # Insert new RawReview
            new_raw = RawReview(
                review_id=review_id,
                source_platform=platform,
                source_review_id=source_rev_id,
                product_id=product_id,
                raw_payload=raw,
                content_hash=content_hash,
                fetch_batch_id=batch_id,
                ingested_at=now
            )
            session.add(new_raw)
            inserted_count += 1
            
    session.commit()
    return {"inserted": inserted_count, "updated": updated_count, "batch_id": batch_id}
