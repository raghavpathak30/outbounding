"""
Enrichment Node implementation.
"""
from typing import Dict, Any
from pipeline.state import PipelineState
from pipeline.adapters.base import AdapterFactory

def enrichment_node(state: PipelineState) -> Dict[str, Any]:
    """
    Enrichment Node: Discovers lead contact details for state["domain"].
    Returns only updated fields to preserve state immutability.
    """
    domain = state.get("domain", "")
    company_name = state.get("company_name")
    company_context = state.get("company_context")

    adapter = AdapterFactory.get_enrichment_adapter()
    try:
        lead_data = adapter.enrich(domain, company_name=company_name, company_context=company_context)
    except TypeError:
        lead_data = adapter.enrich(domain)

    merged_context = lead_data.get("company_context") or company_context

    result = {
        "contact_name": lead_data.get("contact_name"),
        "contact_email": lead_data.get("contact_email"),
        "contact_role": lead_data.get("contact_role"),
        "company_context": merged_context
    }

    for key in [
        "person_name",
        "person_role",
        "person_confidence",
        "person_linkedin",
        "person_source",
        "email_confidence",
        "email_verification_status",
        "enrichment_provider",
        "enrichment_metadata",
    ]:
        if key in lead_data:
            result[key] = lead_data[key]

    return result

