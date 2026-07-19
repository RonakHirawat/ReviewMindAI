import re
import uuid
from datetime import datetime
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from db.models import RawReview, ReviewClean
from langdetect import detect, LangDetectException
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

PREPROCESS_VERSION = "pp-v1"

def normalize_payload(raw_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Step a: Normalize fields from raw payload.
    """
    text_original = raw_payload.get("review_text") or raw_payload.get("text") or ""
    star_rating = int(raw_payload.get("star_rating", 0))
    
    # Parse review date
    review_date_str = raw_payload.get("review_date")
    if review_date_str:
        try:
            # Replace Z with UTC offset if present
            review_date = datetime.fromisoformat(review_date_str.replace("Z", "+00:00"))
        except Exception:
            review_date = datetime.utcnow()
    else:
        review_date = datetime.utcnow()
        
    source_platform = raw_payload.get("source_platform", "unknown")
    product_id = raw_payload.get("product_id", "unknown")
    
    return {
        "text_original": text_original,
        "star_rating": star_rating,
        "review_date": review_date,
        "source_platform": source_platform,
        "product_id": product_id
    }

def detect_language(text: str) -> str:
    """
    Step b: Detect language (en / hi-en / other).
    """
    if not text.strip():
        return "unknown"
    try:
        lang = detect(text)
        # Hinglish check using a set of common romanized Hindi/Hinglish keywords
        hinglish_keywords = {
            "hai", "bohot", "achha", "acha", "yaar", "bhai", "mast", "bekar", "hawa", "garam", 
            "paisa", "wasool", "kiya", "shor", "awaaz", "bhout", "bhoot", "nahin", "nahi", 
            "rakha", "kharab", "lekin", "ishe", "hi", "he", "ko", "se", "pe", "par", "ekdam",
            "bilkul", "hona", "chal", "chalta", "kam", "daam", "mein", "kafi", "bahut", "badhiya",
            "garmi", "thandak", "taap", "garm", "toh", "mili", "gaya"
        }
        words = set(text.lower().split())
        if words.intersection(hinglish_keywords):
            return "hi-en"
        return lang
    except LangDetectException:
        return "unknown"

def calculate_spam_bot_scores(text: str, is_duplicate: bool) -> Tuple[float, float, float]:
    """
    Step d: Rule-based heuristic scorer for spam and bot flags.
    Returns (spam_score, bot_score, trust_score).
    """
    text_strip = text.strip()
    if not text_strip:
        return 1.0, 1.0, 0.0
        
    words = text_strip.lower().split()
    num_words = len(words)
    
    spam_score = 0.0
    bot_score = 0.0
    
    # 1. Length penalty
    if len(text_strip) < 15:
        spam_score += 0.4
        
    # 2. Word repetition penalty
    if num_words > 4:
        unique_ratio = len(set(words)) / num_words
        if unique_ratio < 0.6:
            spam_score += 0.4
            bot_score += 0.3
        if unique_ratio < 0.4:
            spam_score += 0.2
            bot_score += 0.3
            
    # 3. Capitalization penalty
    caps_letters = sum(1 for c in text_strip if c.isupper())
    total_letters = sum(1 for c in text_strip if c.isalpha())
    if total_letters > 5 and (caps_letters / total_letters) > 0.7:
        spam_score += 0.3
        bot_score += 0.2
        
    # 4. Duplicate flag penalty
    if is_duplicate:
        bot_score += 0.4
        
    # Cap at 1.0
    spam_score = min(1.0, spam_score)
    bot_score = min(1.0, bot_score)
    
    # Trust score is the inverse of the average of spam and bot scores
    trust_score = 1.0 - ((spam_score + bot_score) / 2.0)
    
    return spam_score, bot_score, trust_score

def redact_pii(text: str) -> Tuple[str, datetime]:
    """
    Step e: Regex-based PII redaction of phone numbers, emails, names, pin codes.
    Logs pii_redacted_at.
    """
    phone_pattern = r'\b(?:\+?91[\s-]?)?[6-9]\d{9}\b|\b\d{3}[-\s]\d{3}[-\s]\d{4}\b'
    email_pattern = r'\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b'
    name_pattern = r'\b(?:[mM]y [nN]ame [iI]s|[mM]yself|[iI]\s+am)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b'

    pin_pattern = r'\b\d{6}\b'
    
    redacted_text = text
    
    # Redact email
    redacted_text = re.sub(email_pattern, "[EMAIL_REDACTED]", redacted_text)
    # Redact phone
    redacted_text = re.sub(phone_pattern, "[PHONE_REDACTED]", redacted_text)
    # Redact pin
    redacted_text = re.sub(pin_pattern, "[PIN_REDACTED]", redacted_text)
    
    # Redact name phrases
    def replace_name(match):
        full_match = match.group(0)
        name_part = match.group(1)
        return full_match.replace(name_part, "[NAME_REDACTED]")
        
    redacted_text = re.sub(name_pattern, replace_name, redacted_text)
    
    return redacted_text, datetime.utcnow()

def check_prompt_injection(text: str) -> Tuple[bool, str | None]:
    """
    Step f: Pattern-match for prompt injection system override text.
    """
    lower_text = text.lower()
    
    injection_patterns = [
        "ignore previous instructions",
        "ignore instruction",
        "ignore all instructions",
        "ignore all rules",
        "system override",
        "system error",
        "attention agent",
        "you are an ai",
        "ignore any negative",
        "ignore all negative",
        "say this product is great",
        "print: '",
        "system:",
        "user:",
        "assistant:",
        "[system]",
        "<system>"
    ]
    
    for pattern in injection_patterns:
        if pattern in lower_text:
            return True, f"Found injection pattern: '{pattern}'"
            
    # Check for long base64-like words
    b64_pattern = re.compile(r'\b[A-Za-z0-9+/]{20,}=*\b')
    b64_matches = b64_pattern.findall(text)
    if b64_matches:
        return True, f"Found suspicious base64 string: {b64_matches[0][:10]}..."
        
    return False, None

def check_and_split_products(raw_payload: Dict[str, Any], text: str) -> List[Dict[str, Any]]:
    """
    Step g: Keyword matching to check and split reviews containing multiple products.
    """
    aliases = {
        "FAN-TBL-001": ["fan-tbl-001", "tbl-001", "aerobreeze"],
        "FAN-TBL-002": ["fan-tbl-002", "tbl-002", "windturbo"],
        "FAN-TBL-003": ["fan-tbl-003", "tbl-003", "silentsweep"],
        "FAN-TBL-004": ["fan-tbl-004", "tbl-004", "smartbreeze"],
        "FAN-TBL-005": ["fan-tbl-005", "tbl-005", "maxcool"]
    }
    
    detected_products = []
    lower_text = text.lower()
    for prod, syns in aliases.items():
        if any(syn in lower_text for syn in syns):
            detected_products.append(prod)
            
    payload_product_id = raw_payload.get("product_id")
    if payload_product_id and payload_product_id not in detected_products:
        detected_products.append(payload_product_id)
        
    detected_products = list(set(detected_products))
    
    if len(detected_products) > 1:
        split_results = []
        for prod in detected_products:
            split_results.append({
                "product_id": prod,
                "product_ambiguous": True
            })
        return split_results
    else:
        prod = detected_products[0] if detected_products else (payload_product_id or "unknown")
        return [{
            "product_id": prod,
            "product_ambiguous": False
        }]

def compute_deduplication(normalized_reviews: List[Dict[str, Any]]):
    """
    Step c: Exact + near-duplicate detection grouped by (product_id, source_platform).
    Assigns dedupe_group_id in place.
    """
    # Group indices by (product_id, source_platform)
    groups = {}
    for idx, r in enumerate(normalized_reviews):
        key = (r["product_id"], r["source_platform"])
        if key not in groups:
            groups[key] = []
        groups[key].append(idx)
        
    for key, indices in groups.items():
        n = len(indices)
        if n == 0:
            continue
            
        texts = [normalized_reviews[idx]["text_original"] for idx in indices]
        
        # Exact duplicates first
        exact_groups = {}
        for list_pos, text in enumerate(texts):
            if text in exact_groups:
                exact_groups[text].append(indices[list_pos])
            else:
                exact_groups[text] = [indices[list_pos]]
                
        assigned_exact = set()
        for text, idx_list in exact_groups.items():
            if len(idx_list) > 1:
                group_id = f"exact-{str(uuid.uuid4())[:8]}"
                for idx in idx_list:
                    normalized_reviews[idx]["dedupe_group_id"] = group_id
                    assigned_exact.add(idx)
                    
        # Near duplicates check for all in the group
        if n > 1:
            try:
                vectorizer = TfidfVectorizer()
                tfidf_matrix = vectorizer.fit_transform(texts)
                cosine_sim = cosine_similarity(tfidf_matrix)
                
                visited = set()
                for i in range(n):
                    idx_i = indices[i]
                    if idx_i in visited:
                        continue
                    
                    cluster_indices = [idx_i]
                    for j in range(i + 1, n):
                        idx_j = indices[j]
                        if idx_j not in visited and cosine_sim[i, j] >= 0.95:
                            cluster_indices.append(idx_j)
                            
                    if len(cluster_indices) > 1:
                        # Cluster found
                        # Find existing dedupe group id if any
                        group_id = None
                        for idx in cluster_indices:
                            if normalized_reviews[idx].get("dedupe_group_id"):
                                group_id = normalized_reviews[idx]["dedupe_group_id"]
                                break
                        if not group_id:
                            group_id = f"near-{str(uuid.uuid4())[:8]}"
                            
                        for idx in cluster_indices:
                            normalized_reviews[idx]["dedupe_group_id"] = group_id
                            visited.add(idx)
            except Exception:
                # E.g. empty vocabulary
                pass

def preprocess_reviews(session: Session) -> Dict[str, int]:
    """
    Main pipeline entrypoint. Reads unprocessed raw_reviews, cleans them, and writes to reviews_clean.
    """
    # Fetch all raw reviews
    raw_reviews = session.query(RawReview).all()
    if not raw_reviews:
        return {"processed": 0, "written": 0}
        
    # Get already processed review IDs to compute delta
    # Since we can suffix split reviews with "-product_id", we look at both raw review_id matches and suffix matches
    # To keep it simple: we can look at what is already in reviews_clean.
    # To support clean pipeline reruns, we can also clear the reviews_clean table first if needed,
    # but the prompt says: "reads unprocessed rows from raw_reviews and writes to reviews_clean".
    # An unprocessed row is one where its raw review_id is not represented in reviews_clean.
    existing_clean_ids = {r.review_id for r in session.query(ReviewClean).all()}
    
    # We filter raw_reviews that are not in existing_clean_ids
    unprocessed_raws = []
    for raw in raw_reviews:
        # Check if the raw review_id, or any suffixed variant, already exists
        # In a real environment, we'd check if any row in reviews_clean matches the prefix raw.review_id
        is_processed = False
        for clean_id in existing_clean_ids:
            if clean_id == raw.review_id or clean_id.startswith(f"{raw.review_id}-"):
                is_processed = True
                break
        if not is_processed:
            unprocessed_raws.append(raw)
            
    if not unprocessed_raws:
        return {"processed": 0, "written": 0}
        
    # Phase A: Normalize and prepare records in memory
    normalized_list = []
    for raw in unprocessed_raws:
        norm = normalize_payload(raw.raw_payload)
        norm["raw_review_id"] = raw.review_id
        norm["dedupe_group_id"] = None
        normalized_list.append(norm)
        
    # Phase B: Deduplication on the current batch
    compute_deduplication(normalized_list)
    
    written_count = 0
    # Phase C: Language ID, Spam, PII, Injection, Splits and Write
    for item in normalized_list:
        text = item["text_original"]
        raw_id = item["raw_review_id"]
        
        # Language ID
        lang = detect_language(text)
        
        # PII Redaction
        text_clean, pii_redacted_at = redact_pii(text)
        
        # Prompt Injection
        is_injection, quarantine_reason = check_prompt_injection(text)
        
        # Spam & Bot scoring
        is_dup = item["dedupe_group_id"] is not None
        spam_score, bot_score, trust_score = calculate_spam_bot_scores(text, is_dup)
        is_spam = spam_score > 0.5
        
        # Multi-product split check
        # We check raw_reviews' original payload
        raw_payload = next(r.raw_payload for r in unprocessed_raws if r.review_id == raw_id)
        splits = check_and_split_products(raw_payload, text)
        
        # Write clean reviews
        for i, split in enumerate(splits):
            prod_id = split["product_id"]
            is_ambiguous = split["product_ambiguous"]
            
            # Suffix review_id if we have multiple splits
            if len(splits) > 1:
                clean_id = f"{raw_id}-{prod_id}"
            else:
                clean_id = raw_id
                
            new_clean = ReviewClean(
                review_id=clean_id,
                product_id=prod_id,
                text_clean=text_clean,
                text_original=text,
                language=lang,
                star_rating=item["star_rating"],
                review_date=item["review_date"],
                source_platform=item["source_platform"],
                is_spam=is_spam,
                spam_score=spam_score,
                bot_score=bot_score,
                trust_score=trust_score,
                injection_flag=is_injection,
                quarantine_reason=quarantine_reason,
                dedupe_group_id=item["dedupe_group_id"],
                pii_redacted_at=pii_redacted_at,
                product_ambiguous=is_ambiguous,
                preprocess_version=PREPROCESS_VERSION
            )
            session.add(new_clean)
            written_count += 1
            
    session.commit()
    return {"processed": len(unprocessed_raws), "written": written_count}
