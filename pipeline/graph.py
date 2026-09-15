"""
LangGraph StateGraph assembly for Outbound Pipeline.
"""
import re
from typing import Literal
from langgraph.graph import StateGraph, START, END
from pipeline.state import PipelineState
from pipeline.discovery import discovery_node
from pipeline.enrichment import enrichment_node
from pipeline.drafting import drafting_node
from pipeline.review import review_node, has_review_approval, skip_review_node
from pipeline.delivery import delivery_node
from pipeline.contacted_log import is_already_contacted

EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")

def has_valid_email(state: PipelineState) -> Literal["drafting_node", "skip_node", "skip_contacted_node"]:
    """
    Conditional routing edge after enrichment.
    Bypasses drafting and delivery if already contacted or if no valid email could be discovered.
    """
    domain = state.get("domain", "")
    email = state.get("contact_email")

    if state.get("discover"):
        if is_already_contacted(domain=domain, contact_email=email):
            return "skip_contacted_node"

    if email and isinstance(email, str) and EMAIL_REGEX.match(email.strip()):
        return "drafting_node"
    return "skip_node"

def skip_node(state: PipelineState) -> dict:
    """Fallback node for domains where no valid contact email was found."""
    return {"delivery_status": "skipped_no_email"}

def skip_contacted_node(state: PipelineState) -> dict:
    """Fallback node for targets that have already reached delivery in a prior run."""
    return {"delivery_status": "skipped_already_contacted"}

def build_pipeline_graph():
    """Builds and compiles the production LangGraph StateGraph."""
    builder = StateGraph(PipelineState)

    # Register nodes
    builder.add_node("discovery_node", discovery_node)
    builder.add_node("enrichment_node", enrichment_node)
    builder.add_node("drafting_node", drafting_node)
    builder.add_node("review_node", review_node)
    builder.add_node("delivery_node", delivery_node)
    builder.add_node("skip_node", skip_node)
    builder.add_node("skip_contacted_node", skip_contacted_node)
    builder.add_node("skip_review_node", skip_review_node)

    # Define edges: START -> discovery_node -> enrichment_node
    builder.add_edge(START, "discovery_node")
    builder.add_edge("discovery_node", "enrichment_node")
    builder.add_conditional_edges(
        "enrichment_node",
        has_valid_email,
        {
            "drafting_node": "drafting_node",
            "skip_node": "skip_node",
            "skip_contacted_node": "skip_contacted_node"
        }
    )
    builder.add_edge("drafting_node", "review_node")
    builder.add_conditional_edges(
        "review_node",
        has_review_approval,
        {
            "delivery_node": "delivery_node",
            "skip_review_node": "skip_review_node"
        }
    )
    builder.add_edge("delivery_node", END)
    builder.add_edge("skip_node", END)
    builder.add_edge("skip_contacted_node", END)
    builder.add_edge("skip_review_node", END)

    return builder.compile()

# Precompiled graph instance
pipeline_app = build_pipeline_graph()
