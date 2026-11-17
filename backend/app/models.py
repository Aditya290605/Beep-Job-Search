"""
models.py - Canonical Data Models for Fresher Jobs India
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import re


def generate_normalized_key(company: str, title: str, city: str) -> str:
    """
    Generates a deterministic deduplication key by lowercasing,
    stripping non-alphanumeric characters, and joining company, title, and city.
    Example: ('Razorpay', 'SDE Intern', 'Bangalore') -> 'razorpay:sdeintern:bangalore'
    """
    clean_company = re.sub(r'[^a-z0-9]', '', (company or "").lower())
    clean_title = re.sub(r'[^a-z0-9]', '', (title or "").lower())
    clean_city = re.sub(r'[^a-z0-9]', '', (city or "").lower())
    return f"{clean_company}:{clean_title}:{clean_city}"


@dataclass
class RawJob:
    title: str
    company: str
    location_raw: str
    city: str  # Must not be "Unknown" (dropped if Unknown)
    job_type: str  # 'job' or 'internship'
    apply_url: str
    description: str
    source_name: str
    source_job_id: str
    posted_date: Optional[str] = None  # ISO format string or None
    
    @property
    def normalized_key(self) -> str:
        return generate_normalized_key(self.company, self.title, self.city)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CanonicalJob:
    id: Optional[int] = None
    normalized_key: str = ""
    title: str = ""
    company: str = ""
    location_raw: str = ""
    city: str = ""
    job_type: str = "job"
    posted_date: Optional[datetime] = None
    apply_url: str = ""
    description: str = ""
    source_name: str = ""
    source_job_id: str = ""
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    is_active: bool = True
    
    # Enrichment fields (Phase 4)
    role_tag: str = "Other"
    is_fresher_friendly: bool = True
    min_exp: int = 0
    max_exp: int = 1
    skills: List[str] = field(default_factory=list)
    confidence: float = 1.0
    tagged_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineRunStats:
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    status: str = "running"
    sources_summary: Dict[str, int] = field(default_factory=dict)
    total_fetched: int = 0
    new_posts: int = 0
    duplicates_skipped: int = 0
    tagged_count: int = 0
    failed_count: int = 0
    error_message: Optional[str] = None
