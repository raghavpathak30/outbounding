"""
Review Node implementation: Human-in-the-loop manual review checkpoint.
"""
from typing import Dict, Any, Literal
import os
import sys
from pipeline.state import PipelineState

def review_node(state: PipelineState) -> Dict[str, Any]:
    """
    Review Node: Human judgment gate before delivery staging.
    Prompts the user to [A]pprove, [E]dit, or [S]kip the draft.
    Can be bypassed via state['auto_approve'] or AUTO_APPROVE=true env var.
    """
    auto_approve = state.get("auto_approve")
    if auto_approve is None:
        auto_approve = os.getenv("AUTO_APPROVE", "false").lower() in ["true", "1", "yes"]

    if auto_approve:
        return {"review_status": "approved"}

    domain = state.get("domain", "")
    email = state.get("contact_email", "")
    name = state.get("contact_name", "")
    role = state.get("contact_role", "")
    draft = state.get("email_draft", "")

    # Parse subject line and body from draft if formatted with Subject:
    subject = "Outreach Pitch"
    body = draft
    if draft and draft.startswith("Subject:"):
        parts = draft.split("\n\n", 1)
        subject = parts[0].replace("Subject:", "").strip()
        body = parts[1] if len(parts) > 1 else ""

    print("\n" + "=" * 72)
    print(f" 📋 MANUAL REVIEW CHECKPOINT FOR: {domain}")
    print("=" * 72)
    print(f" • To     : {name} <{email}>")
    print(f" • Role   : {role}")
    if state.get("person_confidence") is not None or state.get("email_confidence") is not None:
        p_conf = f"{state['person_confidence']*100:.0f}%" if state.get("person_confidence") is not None else "N/A"
        e_conf = f"{state['email_confidence']*100:.0f}%" if state.get("email_confidence") is not None else "N/A"
        status = state.get("email_verification_status") or "unverified"
        provider = state.get("enrichment_provider") or "adapter"
        print(f" • Quality: Person Match: {p_conf} | Deliverability: {e_conf} ({status}, via {provider})")
    if state.get("person_linkedin"):
        print(f" • Profile: {state['person_linkedin']}")
    print(f" • Subject: {subject}")
    print("-" * 72)
    print(body)
    print("=" * 72)

    while True:
        try:
            choice = input("\n[Review Action] (a)pprove / (e)dit / (s)kip: ").strip().lower()
        except EOFError:
            choice = "a"

        if choice in ["a", "approve", ""]:
            return {"review_status": "approved"}
        elif choice in ["e", "edit"]:
            print("\nEnter replacement email body (type 'END' on a new line or press Enter twice when done):")
            lines = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if line.strip() == "END":
                    break
                if not line and lines and not lines[-1]:
                    break
                lines.append(line)
            replacement_body = "\n".join(lines).strip()
            if replacement_body:
                updated_draft = f"Subject: {subject}\n\n{replacement_body}"
                return {
                    "review_status": "approved",
                    "email_draft": updated_draft
                }
            else:
                print("No replacement entered. Draft unchanged.")
                return {"review_status": "approved"}
        elif choice in ["s", "skip"]:
            return {
                "review_status": "skipped",
                "delivery_status": "skipped_by_reviewer"
            }
        else:
            print("Invalid input. Please enter 'a' to approve, 'e' to edit, or 's' to skip.")

def has_review_approval(state: PipelineState) -> Literal["delivery_node", "skip_review_node"]:
    """Conditional router checking if human reviewer approved the draft."""
    if state.get("review_status") == "approved":
        return "delivery_node"
    return "skip_review_node"

def skip_review_node(state: PipelineState) -> dict:
    """Terminating node when draft is skipped during human review."""
    return {"delivery_status": "skipped_by_reviewer"}
