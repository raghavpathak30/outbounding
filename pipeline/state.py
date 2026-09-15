"""
Pipeline State Schema Definition.
"""
from typing import TypedDict, Optional, Dict, Any

class PipelineState(TypedDict, total=False):
    """
    Immutable state contract passed across LangGraph nodes.
    Each node returns a dictionary containing only the keys it updates.
    """
    domain: str
    contact_name: Optional[str]
    contact_email: Optional[str]
    contact_role: Optional[str]
    company_context: Optional[Dict[str, Any]]
    company_name: Optional[str]
    discover: Optional[bool]
    company_size: Optional[str]
    resume_context: Dict[str, Any]
    email_draft: Optional[str]
    email_subject: Optional[str]
    auto_approve: Optional[bool]
    review_status: Optional[str]
    delivery_status: Optional[str]
    delivery_error: Optional[str]
    person_name: Optional[str]
    person_role: Optional[str]
    person_confidence: Optional[float]
    person_linkedin: Optional[str]
    person_source: Optional[str]
    email_confidence: Optional[float]
    email_verification_status: Optional[str]
    enrichment_provider: Optional[str]
    enrichment_metadata: Optional[Dict[str, Any]]
