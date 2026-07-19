import os
import json
import uuid
from sqlalchemy.orm import Session
from db import init_db, SessionLocal, RawReview, ReviewClean
from ingestion import ingest_reviews
from preprocessing import preprocess_reviews

def run_pipeline():
    print("=== ReviewMind AI Phase 1 Pipeline Run ===")
    
    # 1. Initialize Database
    print("Initializing Database...")
    init_db()
    
    session = SessionLocal()
    
    try:
        # 2. Ingestion
        data_path = os.path.join("data", "synthetic_reviews.json")
        if not os.path.exists(data_path):
            print(f"Error: {data_path} not found. Please run scripts/generate_synthetic_reviews.py first.")
            return
            
        print(f"Loading synthetic reviews from {data_path}...")
        with open(data_path, "r", encoding="utf-8") as f:
            reviews_list = json.load(f)
            
        print(f"Ingesting {len(reviews_list)} reviews into raw_reviews table...")
        batch_id = str(uuid.uuid4())
        ingest_stats = ingest_reviews(session, reviews_list, batch_id)
        print(f"Ingestion completed: Ingested (New)={ingest_stats['inserted']}, Updated={ingest_stats['updated']}")
        
        # 3. Preprocessing
        print("Running Preprocessing pipeline on unprocessed reviews...")
        preprocess_stats = preprocess_reviews(session)
        print(f"Preprocessing completed: Processed={preprocess_stats['processed']}, Clean reviews written={preprocess_stats['written']}")
        
        # 4. Generate & Print Statistics
        raw_count = session.query(RawReview).count()
        clean_count = session.query(ReviewClean).count()
        
        # Flags analysis
        dupes_count = session.query(ReviewClean).filter(ReviewClean.dedupe_group_id.isnot(None)).count()
        spam_count = session.query(ReviewClean).filter_by(is_spam=True).count()
        
        # PII redaction: compare original text to clean text
        pii_count = session.query(ReviewClean).filter(ReviewClean.text_clean != ReviewClean.text_original).count()
        
        # Prompt injections
        injection_count = session.query(ReviewClean).filter_by(injection_flag=True).count()
        
        # Multi-product / ambiguous product reviews
        multiproduct_count = session.query(ReviewClean).filter_by(product_ambiguous=True).count()
        
        print("\n" + "="*40)
        print("PIPELINE SUMMARY:")
        print(f"Total Raw Reviews in db:         {raw_count}")
        print(f"Total Clean Reviews in db:       {clean_count}")
        print(f"Duplicates (Exact/Near) flagged: {dupes_count}")
        print(f"Spam reviews flagged:            {spam_count}")
        print(f"PII redactions performed:        {pii_count}")
        print(f"Prompt injection attempts:       {injection_count}")
        print(f"Multi-product reviews split/tag: {multiproduct_count}")
        print("="*40)
        
    except Exception as e:
        print(f"Error during pipeline execution: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == "__main__":
    run_pipeline()
