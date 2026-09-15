"""
Drafting Node implementation and Persona Classification.
"""
import json
from pathlib import Path
from typing import Dict, Any
from pipeline.state import PipelineState
from pipeline.adapters.base import AdapterFactory

def load_resume_context() -> Dict[str, Any]:
    resume_path = Path("data/resume.json")
    if resume_path.exists():
        try:
            return json.loads(resume_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def detect_persona(role: str) -> str:
    """Classifies target role into security, ai_ml, or hr_talent persona."""
    r = (role or "").lower()
    if any(k in r for k in ["security", "infra", "ciso", "secops", "crypt", "devsec"]):
        return "security"
    if any(k in r for k in ["ai", "ml", "machine learning", "data science", "llm", "deep learning"]):
        return "ai_ml"
    return "hr_talent"

def drafting_node(state: PipelineState) -> Dict[str, Any]:
    """
    Drafting Node: Adapts resume pitch based on contact_role.
    Returns only the updated email_draft key.
    """
    domain = state.get("domain", "")
    role = state.get("contact_role")
    contact_name = state.get("contact_name")
    company_context = state.get("company_context")
    
    resume_context = state.get("resume_context")
    if not resume_context:
        resume_context = load_resume_context()

    adapter = AdapterFactory.get_drafting_adapter()
    draft_copy = adapter.draft(
        role=role,
        domain=domain,
        resume_context=resume_context,
        contact_name=contact_name,
        company_context=company_context
    )

    return {
        "resume_context": resume_context,
        "email_draft": draft_copy
    }
