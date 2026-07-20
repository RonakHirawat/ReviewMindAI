import os
import sys
from collections import Counter

# Add project root to sys.path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.session import SessionLocal, init_db
from db.models import RawReview, ReviewClean, ReviewAspect, ExtractionRun

def verify():
    session = SessionLocal()
    violations = []
    
    # a) Row count integrity
    raw_count = session.query(RawReview).count()
    clean_count = session.query(ReviewClean).count()
    
    # Verify every raw review is accounted for (direct match or split match prefix)
    clean_ids = [c.review_id for c in session.query(ReviewClean.review_id).all()]
    raw_ids = [r.review_id for r in session.query(RawReview.review_id).all()]
    
    unaccounted_ids = []
    for rid in raw_ids:
        found = any(cid == rid or cid.startswith(rid + "-") for cid in clean_ids)
        if not found:
            unaccounted_ids.append(rid)
            
    if raw_count < 300:
        violations.append(f"raw_reviews count {raw_count} is less than expected synthetic dataset size (309)")
    if clean_count < raw_count:
        violations.append(f"reviews_clean count {clean_count} is less than raw_reviews count {raw_count}")
    if unaccounted_ids:
        violations.append(f"{len(unaccounted_ids)} raw reviews were silently dropped/lost in preprocessing: {unaccounted_ids[:5]}")
        
    # b) Flag sanity
    injection_count = session.query(ReviewClean).filter(ReviewClean.injection_flag == True).count()
    dedupe_count = session.query(ReviewClean).filter(ReviewClean.dedupe_group_id.isnot(None)).count()
    pii_count = session.query(ReviewClean).filter(ReviewClean.pii_redacted_at.isnot(None)).count()
    ambiguous_count = session.query(ReviewClean).filter(ReviewClean.product_ambiguous == True).count()
    
    if injection_count == 0:
        violations.append("injection_flag count is exactly 0 in reviews_clean (preprocessing step failed)")
    if dedupe_count == 0:
        violations.append("dedupe_group_id count is exactly 0 in reviews_clean (deduplication failed)")
    if pii_count == 0:
        violations.append("pii_redacted_at count is exactly 0 in reviews_clean (PII redaction failed)")
    if ambiguous_count == 0:
        violations.append("product_ambiguous count is exactly 0 in reviews_clean (multi-product split failed)")
        
    # c) Injection containment check
    injections = session.query(ReviewClean).filter(ReviewClean.injection_flag == True).all()
    injection_containment_violation = False
    injection_display_list = []
    
    for rev in injections:
        aspects = session.query(ReviewAspect).filter_by(review_id=rev.review_id).all()
        bad_words = ["ignore previous", "say this product is", "perfect", "ignore instructions"]
        for aspect in aspects:
            phrase_lower = aspect.aspect_phrase_raw.lower()
            span_lower = aspect.verbatim_span.lower()
            if any(w in phrase_lower or w in span_lower for w in bad_words):
                injection_containment_violation = True
        injection_display_list.append((rev.text_clean, [a.aspect_phrase_raw for a in aspects]))
        
    if injection_containment_violation:
        violations.append("Injected instruction leaked into extracted aspects/verbatim spans")
        
    # d) Verbatim-span integrity (critical)
    verbatim_span_violation_count = 0
    all_aspects = session.query(ReviewAspect).all()
    for aspect in all_aspects:
        rev_clean = session.query(ReviewClean).filter_by(review_id=aspect.review_id).first()
        if not rev_clean:
            violations.append(f"Aspect {aspect.id} has no corresponding review_clean row")
            continue
        if aspect.verbatim_span not in rev_clean.text_clean:
            verbatim_span_violation_count += 1
            print(f"[VERBATIM_VIOLATION] Review ID: {aspect.review_id}")
            print(f"  Attempted verbatim_span: \"{aspect.verbatim_span}\"")
            print(f"  Clean Review Text:      \"{rev_clean.text_clean}\"")
            
    if verbatim_span_violation_count > 0:
        violations.append(f"{verbatim_span_violation_count} aspects violated verbatim-span integrity (not exact substrings)")
        
    # e) Aspect coverage sanity
    total_aspects = len(all_aspects)
    clean_reviews = session.query(ReviewClean).all()
    avg_aspects = total_aspects / len(clean_reviews) if clean_reviews else 0
    
    zero_aspect_count = 0
    for rev in clean_reviews:
        count = session.query(ReviewAspect).filter_by(review_id=rev.review_id).count()
        if count == 0:
            zero_aspect_count += 1
            
    # f) Aspect phrase variety
    all_phrases = [a.aspect_phrase_raw for a in all_aspects]
    phrase_counts = Counter(all_phrases).most_common(20)
    
    # g) Cost/latency sanity
    runs = session.query(ExtractionRun).all()
    total_runs = len(runs)
    total_input_tokens = sum(r.input_tokens for r in runs)
    total_output_tokens = sum(r.output_tokens for r in runs)
    avg_latency = sum(r.latency_ms for r in runs) / total_runs if total_runs > 0 else 0
    
    # Check if this is local inference (Ollama)
    is_local_inference = any(r.extraction_model_version.startswith("ollama-") for r in runs)
    
    if is_local_inference:
        cost_inr = 0.0
        cost_display = "INR 0.0000 (Local Inference: True)"
    else:
        cost_inr = (total_input_tokens / 1_000_000.0) * 8.0 + (total_output_tokens / 1_000_000.0) * 32.0
        cost_display = f"INR 0.0000 (Free Tier) [Paid equivalent: INR {cost_inr:.4f}]"
    
    # Print the verification report
    print("\n" + "=" * 60)
    print("           ReviewMind AI - Pipeline Verification Report")
    print("=" * 60)
    print(f"a) Row Counts:")
    print(f"   - Raw Reviews: {raw_count}")
    print(f"   - Clean Reviews: {clean_count}")
    print(f"   - Unaccounted IDs: {len(unaccounted_ids)}")
    print(f"b) Flag Sanity Counts:")
    print(f"   - Injection Flag Count: {injection_count}")
    print(f"   - Deduplicated (Dupes) Count: {dedupe_count}")
    print(f"   - PII Redacted Count: {pii_count}")
    print(f"   - Product Ambiguous Count: {ambiguous_count}")
    print(f"c) Injection Containment Check (Sample of 3 cases):")
    for idx, (text, aspects_list) in enumerate(injection_display_list[:3]):
        print(f"   Case #{idx+1}:")
        print(f"     Review:  \"{text}\"")
        print(f"     Aspects: {aspects_list}")
    print(f"d) Verbatim Span Violations: {verbatim_span_violation_count}")
    print(f"e) Aspect Coverage Sanity:")
    print(f"   - Total Aspects: {total_aspects}")
    print(f"   - Avg Aspects/Review: {avg_aspects:.2f}")
    print(f"   - Clean Reviews with 0 Aspects: {zero_aspect_count}")
    print(f"f) Aspect Phrase Variety (Top 20 Distinct):")
    for phrase, count in phrase_counts:
        print(f"     - \"{phrase}\": {count}")
    print(f"g) Cost / Latency Sanity:")
    print(f"   - Total Calls Logged: {total_runs}")
    print(f"   - Total Tokens: {total_input_tokens + total_output_tokens} (In: {total_input_tokens}, Out: {total_output_tokens})")
    print(f"   - Total Estimated Cost: {cost_display}")
    print(f"   - Avg Latency: {avg_latency:.1f} ms")
    print("=" * 60)
    
    if not violations:
        print("PHASE 1+2 VERIFICATION: PASS")
    else:
        print("PHASE 1+2 VERIFICATION: FAIL")
        print("Violations:")
        for v in violations:
            print(f"  - {v}")
    print("=" * 60)
    
    session.close()

if __name__ == "__main__":
    verify()
