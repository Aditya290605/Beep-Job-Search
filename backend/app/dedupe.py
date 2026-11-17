"""
backend/app/dedupe.py - Deterministic & Fuzzy Deduplication Engine

Enforces deduplication entirely in PLAIN CODE (no LLM tokens spent):
1. Level 1 (Deterministic): Exact normalized key (company:title:city).
2. Level 2 (Fuzzy Near-Match): Domain-aware company normalization (stripping corporate
   suffixes like "Pvt Ltd", "Technologies"), title abbreviation expansion ("SDE" -> "software development engineer"),
   and token-sort similarity with guardrails (city and job-type preservation).
"""

import re
from typing import Optional, Tuple, List, Dict, Any
from app.models import RawJob

# Attempt to import rapidfuzz; fallback to difflib if not installed
HAS_RAPIDFUZZ = False
try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    import difflib
    HAS_RAPIDFUZZ = False

# Corporate suffixes to strip from company names
CORP_SUFFIXES = [
    r"\bprivate limited\b", r"\bpvt ltd\b", r"\bltd\b", r"\binc\b",
    r"\bcorp\b", r"\bcorporation\b", r"\btechnologies\b", r"\btechnology\b",
    r"\bsolutions\b", r"\bsoftware\b", r"\bindia\b", r"\bllc\b"
]
CORP_REGEX = re.compile("|".join(CORP_SUFFIXES), re.IGNORECASE)

# Standard tech title abbreviations
ABBREVIATIONS = {
    r"\bsde\b": "software development engineer",
    r"\bswe\b": "software engineer",
    r"\bqa\b": "quality assurance",
    r"\bml\b": "machine learning",
    r"\bai\b": "artificial intelligence",
    r"\bfe\b": "frontend",
    r"\bbe\b": "backend"
}


def normalize_company(name: str) -> str:
    """
    Cleans company names by lowercasing, stripping corporate noise, and removing special chars.
    Example: 'Razorpay Software Private Limited' -> 'razorpay'
    Example: 'Dreamplug Technologies (CRED)' -> 'cred'
    """
    if not name:
        return ""
    clean = name.lower()
    # Check parenthetical company name first, e.g. "Dreamplug Technologies (CRED)"
    paren_match = re.search(r'\((.*?)\)', clean)
    if paren_match:
        inner = paren_match.group(1).strip()
        if len(inner) > 1:
            clean = inner

    # Strip corporate noise
    clean = CORP_REGEX.sub(" ", clean)
    clean = re.sub(r'[^a-z0-9\s]', ' ', clean)
    return " ".join(clean.split())


def normalize_title(title: str) -> str:
    """
    Normalizes job titles by expanding tech acronyms and removing punctuation/batch noise.
    Example: 'SDE Intern - 2026 Batch' -> 'software development engineer intern 2026'
    """
    if not title:
        return ""
    clean = title.lower()
    for pattern, expanded in ABBREVIATIONS.items():
        clean = re.sub(pattern, expanded, clean)
    # Remove punctuation
    clean = re.sub(r'[^a-z0-9\s]', ' ', clean)
    return " ".join(clean.split())


def compute_string_similarity(s1: str, s2: str) -> float:
    """
    Computes token-sort similarity score between two strings (0.0 to 100.0).
    Uses rapidfuzz.fuzz.token_sort_ratio if available, otherwise difflib.
    """
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 100.0

    if HAS_RAPIDFUZZ:
        return float(fuzz.token_sort_ratio(s1, s2))
    else:
        # Token sort with difflib
        w1 = " ".join(sorted(s1.split()))
        w2 = " ".join(sorted(s2.split()))
        return difflib.SequenceMatcher(None, w1, w2).ratio() * 100.0


def is_duplicate_pair(job1_company: str, job1_title: str, job1_city: str, job1_type: str,
                      job2_company: str, job2_title: str, job2_city: str, job2_type: str,
                      company_threshold: float = 85.0,
                      title_threshold: float = 80.0) -> Tuple[bool, str]:
    """
    Determines whether two job postings are duplicates of the same underlying role.
    
    Guardrails (Hard Constraints):
    - Cities MUST match (or both Remote). Different cities are never duplicates.
    - Job types MUST match ('job' vs 'internship' are distinct positions).
    - Level numbers MUST match (e.g. 'Engineer I' vs 'Engineer II' are distinct).
    """
    # Guard 1: City must match
    if (job1_city or "").lower() != (job2_city or "").lower():
        return False, "Different cities"

    # Guard 2: Job type must match (intern vs full-time)
    if (job1_type or "").lower() != (job2_type or "").lower():
        return False, "Different job types (internship vs full-time)"

    # Guard 3: Seniority numeral mismatch check (e.g., I vs II, 1 vs 2)
    t1_lower = job1_title.lower()
    t2_lower = job2_title.lower()
    numeral_patterns = [r"\b1\b|\bi\b", r"\b2\b|\bii\b", r"\b3\b|\biii\b"]
    for p in numeral_patterns:
        has1 = bool(re.search(p, t1_lower))
        has2 = bool(re.search(p, t2_lower))
        if has1 != has2:
            return False, "Different seniority numerals"

    # Normalize company and titles
    c1 = normalize_company(job1_company)
    c2 = normalize_company(job2_company)
    company_score = compute_string_similarity(c1, c2)
    if company_score < company_threshold:
        return False, f"Company mismatch ({company_score:.1f}% < {company_threshold}%)"

    t1 = normalize_title(job1_title)
    t2 = normalize_title(job2_title)
    title_score = compute_string_similarity(t1, t2)
    if title_score < title_threshold:
        return False, f"Title mismatch ({title_score:.1f}% < {title_threshold}%)"

    return True, f"Match: company={company_score:.0f}%, title={title_score:.0f}%"


class DeduplicationIndex:
    """
    In-memory indexing structure partitioned by city to perform fast,
    accurate near-duplicate detection across sources without O(N^2) global scan.
    """
    def __init__(self, company_threshold: float = 85.0, title_threshold: float = 80.0):
        self.company_threshold = company_threshold
        self.title_threshold = title_threshold
        # Key: city -> List of tuples (job_id, company, title, job_type, apply_url)
        self._city_buckets: Dict[str, List[Dict[str, Any]]] = {}

    def index_job(self, job_id: int, company: str, title: str, city: str, job_type: str, apply_url: str):
        city_key = (city or "").lower()
        if city_key not in self._city_buckets:
            self._city_buckets[city_key] = []
        self._city_buckets[city_key].append({
            "job_id": job_id,
            "company": company,
            "title": title,
            "city": city,
            "job_type": job_type,
            "apply_url": apply_url
        })

    def find_duplicate(self, candidate: RawJob) -> Optional[int]:
        """
        Searches for a near-duplicate of candidate in the same city bucket.
        Returns existing job_id if matched, or None.
        """
        city_key = (candidate.city or "").lower()
        bucket = self._city_buckets.get(city_key, [])

        for existing in bucket:
            is_dupe, reason = is_duplicate_pair(
                candidate.company, candidate.title, candidate.city, candidate.job_type,
                existing["company"], existing["title"], existing["city"], existing["job_type"],
                company_threshold=self.company_threshold,
                title_threshold=self.title_threshold
            )
            if is_dupe:
                return existing["job_id"]

        return None
