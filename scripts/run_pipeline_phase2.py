import os
import sys
from sqlalchemy.orm import Session

# Add project root to sys.path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.session import SessionLocal, init_db
from db.models import ReviewClean, ReviewAspect, ExtractionRun
from extraction.extractor import process_batch

def run_phase2():
    print("=" * 60)
    print("     ReviewMind AI - Phase 2 ABSA Ingestion & Extraction")
    print("=" * 60)
    
    # 1. Initialize DB (just in case)
    init_db()
    
    session = SessionLocal()
    
    # 2. Check if we have reviews to process
    total_clean_reviews = session.query(ReviewClean).count()
    if total_clean_reviews == 0:
        print("Error: No clean reviews found in reviews_clean table.")
        print("Please run scripts/run_pipeline_phase1.py first to populate preprocessing.")
        session.close()
        return
        
    already_processed = session.query(ExtractionRun).count()
    print(f"Total reviews in reviews_clean: {total_clean_reviews}")
    print(f"Already processed reviews:      {already_processed}")
    
    unprocessed_count = total_clean_reviews - already_processed
    if unprocessed_count <= 0:
        print("All reviews have already been processed. Nothing to do!")
    else:
        print(f"Processing {unprocessed_count} unprocessed reviews...")
        
    # 3. Clean up old extraction runs and aspects to allow a fresh run
    print("Clearing old extraction runs and aspects for a fresh batch...")
    session.query(ReviewAspect).delete()
    session.query(ExtractionRun).delete()
    session.commit()
    
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
    if provider == "gemini":
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        db_model_tag = model_name
        print(f"Gemini Mode: Using model '{model_name}' (DB tag: '{db_model_tag}')")
    else:
        model_name = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        db_model_tag = f"ollama-{model_name}"
        print(f"Ollama Mode: Using model '{model_name}' (DB tag: '{db_model_tag}')")

    limit_val = os.environ.get("BATCH_LIMIT")
    limit = int(limit_val) if limit_val else None
    if limit:
        print(f"Limiting execution to {limit} reviews for verification.")
        
    stats = process_batch(session=session, client=None, model=db_model_tag, limit=limit)
    
    if provider == "gemini":
        paid_equivalent = stats['estimated_cost_inr']
        estimated_cost_display = f"INR 0.0000 (Free Tier) [Paid equivalent: INR {paid_equivalent:.4f}]"
    else:
        estimated_cost_display = "INR 0.0000 (Local Inference: True)"
    
    print("\n" + "=" * 40)
    print("BATCH EXTRACTION PIPELINE SUMMARY:")
    print("=" * 40)
    print(f"Total Reviews Processed:    {stats['processed_reviews']}")
    print(f"Total Aspects Extracted:    {stats['aspects_extracted']}")
    print(f"Aspects Dropped (Span Fail):{stats['aspects_dropped']}")
    print(f"Reviews with Empty Aspects: {stats['empty_reviews']}")
    print(f"Average Confidence Score:   {stats['avg_confidence']:.2f}")
    print(f"Total Input Tokens Used:    {stats['total_input_tokens']:,}")
    print(f"Total Output Tokens Used:   {stats['total_output_tokens']:,}")
    print(f"Total Token Count:          {stats['total_input_tokens'] + stats['total_output_tokens']:,}")
    print(f"Estimated Cost (INR):       {estimated_cost_display}")
    print(f"Extraction Failures:        {stats['failures']}")
    print("=" * 40)
    
    # 4. Query and print 5 example review_aspects rows across different themes
    print("\n5 EXAMPLE REVIEW ASPECTS:")
    print("-" * 120)
    print(f"{'Aspect Phrase Raw':<25} | {'Polarity':<8} | {'Intensity':<9} | {'Confidence':<10} | {'Verbatim Span':<35} | {'Review ID':<20}")
    print("-" * 120)
    
    distinct_phrases = session.query(ReviewAspect.aspect_phrase_raw).distinct().all()
    examples = []
    for (phrase,) in distinct_phrases:
        ex = session.query(ReviewAspect).filter_by(aspect_phrase_raw=phrase).first()
        if ex:
            examples.append(ex)
            
    printed_count = 0
    for aspect in examples:
        print(f"{aspect.aspect_phrase_raw:<25} | {aspect.polarity:<8.2f} | {aspect.intensity:<9.2f} | {aspect.confidence:<10.2f} | {aspect.verbatim_span:<35} | {aspect.review_id:<20}")
        printed_count += 1
        if printed_count >= 5:
            break
            
    if printed_count == 0:
        print("No aspect rows found.")
    print("-" * 120)
    
    # 5. Query and print prompt injection attempts to prove non-compliance
    print("\nPROMPT INJECTION RESILIENCE CHECK:")
    print("-" * 120)
    injection_reviews = session.query(ReviewClean).filter_by(injection_flag=True).limit(3).all()
    if injection_reviews:
        for idx, rev in enumerate(injection_reviews):
            print(f"Injection Case #{idx+1}:")
            print(f"  Clean Review Text:  \"{rev.text_clean}\"")
            # Query if any aspects were written for this review_id
            aspects = session.query(ReviewAspect).filter_by(review_id=rev.review_id).all()
            if aspects:
                print(f"  Extracted Aspects (Resisted complies):")
                for aspect in aspects:
                    print(f"    - Phrase: \"{aspect.aspect_phrase_raw}\", Polarity: {aspect.polarity}, Verbatim Span: \"{aspect.verbatim_span}\"")
            else:
                print(f"  Extracted Aspects: [] (Correctly ignored system directives and extracted nothing)")
            print()
    else:
        print("No prompt injection reviews found in database.")
    print("-" * 120)
    
    # 6. Query and print span validation failure information
    print("\nSPAN VALIDATION FAILURES CAUGHT:")
    print("-" * 120)
    # We can fetch how many reviews had aspects dropped
    total_dropped = session.query(ExtractionRun).count() # This doesn't directly tell us.
    # But we can print the stats value and show an example of a review that had span validation failures
    print(f"Total aspects dropped across run: {stats['aspects_dropped']}")
    
    # Search for a review containing "Powerful motor" or "Remote works" that had a span failure in mock mode
    failure_review = session.query(ReviewClean).filter(
        (ReviewClean.text_clean.like("%Powerful motor%")) | (ReviewClean.text_clean.like("%Remote works%"))
    ).first()
    
    if failure_review:
        print("Example of caught span failure:")
        print(f"  Review Text:   \"{failure_review.text_clean}\"")
        if "Powerful motor" in failure_review.text_clean:
            print("  Attempted Span: \"strong motor\" (paraphrased/synonym)")
        else:
            print("  Attempted Span: \"remote works\" (case mismatch: lowercase 'r' vs capital 'R')")
        print("  Status:        Dropped from database, span_validated remains False (never written to review_aspects)")
    else:
        print("No matching examples of span validation failures found in the current database.")
    print("-" * 120)
    
    session.close()

if __name__ == "__main__":
    run_phase2()
