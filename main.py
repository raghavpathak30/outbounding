#!/usr/bin/env python3
"""
Outbound Lead Pipeline CLI Entrypoint.
Supports automated company discovery (--discover N), volume cap enforcement,
manual domain testing (--domain), batch execution (--batch), and safety staging.
"""
import os
import sys
import time
import logging
import argparse
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment configuration
load_dotenv()

from pipeline.graph import pipeline_app
from pipeline.drafting import load_resume_context
from pipeline.adapters.base import AdapterFactory
from pipeline.contacted_log import check_volume_caps, is_already_contacted
from pipeline.config import (
    GEMINI_DRAFTING_MODEL,
    GEMINI_DISCOVERY_MODEL,
    GEMINI_PERSON_RESEARCH_MODEL,
    MIN_EMAIL_CONFIDENCE,
    ALLOW_ACCEPT_ALL,
    DailyQuotaExhaustedError,
)

logger = logging.getLogger("pipeline.main")

def print_runtime_banner(dry_run: bool, confirm_live: bool, auto_approve: bool = False, company_size: str = "any"):
    discovery_mode = os.getenv("DISCOVERY_MODE", "stub").upper()
    enrichment_mode = os.getenv("ENRICHMENT_MODE", os.getenv("APOLLO_MODE", "two_stage")).upper()
    drafting_mode = os.getenv("DRAFTING_MODE", "stub").upper()
    delivery_mode = os.getenv("DELIVERY_MODE", "stub").upper()
    review_mode = "Auto-Approved (Bypass Prompt)" if auto_approve else "Interactive Prompt (Human Gate)"
    
    cap_info = check_volume_caps()

    print("=" * 72)
    print(" 🚀 LANGGRAPH OUTBOUND PIPELINE - RUNTIME CONFIGURATION")
    print("=" * 72)
    if discovery_mode == "RESEARCH":
        disc_desc = f"Gemini Grounded Search ({GEMINI_DISCOVERY_MODEL}, Size: {company_size})"
    elif discovery_mode == "LIVE":
        disc_desc = f"Apollo Org Search (Size: {company_size})"
    else:
        disc_desc = f"Rotating Stub (Size: {company_size})"
    print(f" • Discovery Node   : [{discovery_mode}] - {disc_desc}")
    if enrichment_mode in ["TWO_STAGE", "LIVE", "RESEARCH"]:
        enrich_desc = f"Decoupled (Stage 1: {GEMINI_PERSON_RESEARCH_MODEL} Grounding | Stage 2: Hunter Email Finder, Min Conf: {MIN_EMAIL_CONFIDENCE}%, Catch-All: {ALLOW_ACCEPT_ALL})"
    else:
        enrich_desc = "Deterministic Mock Fixtures (Zero Fabrication)"
    print(f" • Enrichment Node  : [{enrichment_mode}] - {enrich_desc}")
    print(f" • Drafting Node    : [{drafting_mode}] - Live Gemini Model ({GEMINI_DRAFTING_MODEL})")
    print(f" • Review Gate      : [{review_mode}]")
    print(f" • Delivery Node    : [{delivery_mode}] - Instantly/Lemlist Webhook Stager")
    print(f" • DRY_RUN Active   : [{dry_run}] (Hardcoded staging safe)")
    print(f" • Confirm Live Flag: [{confirm_live}]")
    print(f" • Volume Caps      : [Day: {cap_info['sends_today']}/{cap_info['max_day']} used | Week: {cap_info['sends_week']}/{cap_info['max_week']} used]")
    if not dry_run and confirm_live:
        print(" ⚠️  WARNING: LIVE NETWORK DISPATCH IS ACTIVATED")
    else:
        print(" 🛡️  SAFETY: Zero live sends. Outbound payloads staged to staged_deliveries/.")
    print("=" * 72)

def print_draft_preview(domain: str, result: dict):
    draft_content = result.get("email_draft", "")
    subject = result.get("email_subject")
    body_content = draft_content

    if draft_content.startswith("Subject:"):
        parts = draft_content.split("\n\n", 1)
        subject = parts[0].replace("Subject:", "").strip()
        body_content = parts[1] if len(parts) > 1 else ""

    if not subject:
        subject = f"Technical Collaboration & Opportunities at {domain}"

    print(f"\n  ┌─── [FULL EMAIL DRAFT FOR {domain}] ──────────────────────────────")
    print(f"  │ Subject: {subject}")
    print(f"  │ To: {result.get('contact_name')} <{result.get('contact_email')}>")
    print(f"  │ Role: {result.get('contact_role')}")
    print(f"  ├{'─'*68}")
    for line in body_content.splitlines():
        print(f"  │ {line}")
    print(f"  └─── [END OF DRAFT] ────────────────────────────────────────────────\n")

def run_single_domain(domain: str, resume_context: dict, auto_approve: bool = False) -> dict:
    print(f"\n[*] Processing target domain: {domain}")
    initial_state = {
        "domain": domain,
        "resume_context": resume_context,
        "auto_approve": auto_approve
    }
    result = pipeline_app.invoke(initial_state)
    
    print(f"  ✓ Contact Name   : {result.get('contact_name')}")
    print(f"  ✓ Contact Email  : {result.get('contact_email')}")
    print(f"  ✓ Contact Role   : {result.get('contact_role')}")
    print(f"  ✓ Review Status  : {result.get('review_status')}")
    print(f"  ✓ Delivery Status: {result.get('delivery_status')}")
    if result.get("delivery_error"):
        print(f"  ✗ Delivery Error : {result.get('delivery_error')}")
    
    if result.get("email_draft"):
        print_draft_preview(domain, result)
    return result

def run_discovered_flow(
    target_count: int,
    company_size: str,
    resume_context: dict,
    auto_approve: bool = False,
    max_attempts: Optional[int] = None
):
    cap_info = check_volume_caps()
    effective_allowance = cap_info["effective_allowance"]
    max_day = cap_info["max_day"]
    max_week = cap_info["max_week"]
    sends_today = cap_info["sends_today"]
    sends_week = cap_info["sends_week"]

    if effective_allowance <= 0:
        print(f"\n🚫 [VOLUME CAP EXCEEDED] Cannot process discovered targets.")
        print(f"   • Daily Cap: {sends_today}/{max_day} used (0 remaining)")
        print(f"   • Weekly Cap: {sends_week}/{max_week} used (0 remaining)")
        print(f"   • Skipped all {target_count} requested candidate(s) to enforce volume invariants.")
        return

    allowed_count = min(target_count, effective_allowance)
    if allowed_count < target_count:
        skipped_count = target_count - allowed_count
        print(f"\n⚠️  [VOLUME CAP THROTTLED] Requested {target_count} companies, but remaining allowance is {allowed_count}.")
        print(f"   • Daily Cap: {sends_today}/{max_day} used ({cap_info['remaining_day']} remaining)")
        print(f"   • Weekly Cap: {sends_week}/{max_week} used ({cap_info['remaining_week']} remaining)")
        print(f"   • Skipping {skipped_count} candidate(s) to adhere to volume limits.")

    # Calculate MAX_DISCOVERY_ATTEMPTS (default: 3x requested count)
    configured_max = os.getenv("MAX_DISCOVERY_ATTEMPTS")
    if max_attempts is None:
        if configured_max:
            try:
                max_attempts = int(configured_max)
            except ValueError:
                max_attempts = allowed_count * 3
        else:
            max_attempts = allowed_count * 3

    adapter = AdapterFactory.get_discovery_adapter()
    processed_count = 0
    skipped_contacted_count = 0
    candidate_pool = []
    attempts = 0
    evaluated_domains = set()

    print(f"\n🔍 Discovering {allowed_count} new, uncontacted target companies (size: '{company_size}', max attempts: {max_attempts})...")

    while processed_count < allowed_count:
        if attempts >= max_attempts:
            err_msg = f"could not find {allowed_count} new uncontacted candidates after {max_attempts} attempts"
            print(f"\n❌ [DISCOVERY ATTEMPTS EXCEEDED] {err_msg}")
            raise RuntimeError(err_msg)

        if not candidate_pool:
            try:
                batch = adapter.discover(limit=max(allowed_count * 2, 10), company_size=company_size)
            except DailyQuotaExhaustedError:
                logger.error("Discovery run halted immediately due to Gemini daily quota exhaustion.")
                raise
            if not batch:
                err_msg = f"could not find {allowed_count} new uncontacted candidates after {attempts} attempts"
                print(f"\n❌ [DISCOVERY EXHAUSTED] {err_msg}")
                raise RuntimeError(err_msg)
            candidate_pool.extend(batch)

        cand = candidate_pool.pop(0)
        raw_domain = cand.get("domain")
        if not raw_domain:
            continue

        attempts += 1

        domain = raw_domain.strip().lower()
        if domain in evaluated_domains:
            logger.info(f"Discovered domain {domain} was already evaluated in this session. Skipping duplicate...")
            continue
        evaluated_domains.add(domain)

        if is_already_contacted(domain=domain):
            logger.info(f"Discovered domain {domain} was previously contacted. Skipping and finding replacement...")
            skipped_contacted_count += 1
            continue

        print(f"\n[*] Processing candidate ({processed_count + 1}/{allowed_count}, attempt {attempts}/{max_attempts}): {cand.get('company_name', domain)} ({domain})")
        initial_state = {
            "domain": domain,
            "company_name": cand.get("company_name"),
            "company_context": cand.get("company_context"),
            "resume_context": resume_context,
            "auto_approve": auto_approve,
            "discover": True,
            "company_size": company_size
        }
        try:
            result = pipeline_app.invoke(initial_state)
        except DailyQuotaExhaustedError:
            logger.error(f"Processing halted for {domain} due to Gemini daily quota exhaustion.")
            raise

        delivery_status = result.get("delivery_status")
        print(f"  ✓ Contact Name   : {result.get('contact_name')}")
        print(f"  ✓ Contact Email  : {result.get('contact_email')}")
        print(f"  ✓ Contact Role   : {result.get('contact_role')}")
        print(f"  ✓ Review Status  : {result.get('review_status')}")
        print(f"  ✓ Delivery Status: {delivery_status}")

        if delivery_status in ["staged", "sent"]:
            processed_count += 1
            if result.get("email_draft"):
                print_draft_preview(domain, result)
        elif delivery_status == "skipped_already_contacted":
            print(f"  ↪ [REPLACEMENT REQUIRED] Contact for {domain} was previously contacted. Finding replacement candidate...")
            skipped_contacted_count += 1
        elif delivery_status == "skipped_no_email":
            if result.get("person_name"):
                print(f"  ↪ [REPLACEMENT REQUIRED] Found leader '{result['person_name']}' at {domain}, but no deliverable email verified (min score: {MIN_EMAIL_CONFIDENCE}%). Finding replacement...")
            else:
                print(f"  ↪ [REPLACEMENT REQUIRED] No verified technical leader found for {domain}. Finding replacement candidate...")
        else:
            print(f"  ↪ Candidate ended with status '{delivery_status}'. Finding replacement candidate...")

    print(f"\n🏁 Discovery run complete: {processed_count}/{allowed_count} successfully processed ({attempts} attempts evaluated).")
    if skipped_contacted_count > 0:
        print(f"   ℹ️  {skipped_contacted_count} previously contacted candidate(s) skipped and replaced.")

def main():
    parser = argparse.ArgumentParser(description="LangGraph Outbound Pipeline CLI")
    parser.add_argument("--discover", type=int, default=None, help="Discover and process N new uncontacted companies")
    parser.add_argument("--company-size", type=str, choices=["small", "any", "established"], default=None, help="Company size filter for discovery (small, any, established)")
    parser.add_argument("--max-attempts", type=int, default=None, help="Maximum discovery candidate attempts before failing (default: 3x --discover count)")
    parser.add_argument("--discovery-mode", type=str, choices=["stub", "live", "research"], default=None, help="Discovery adapter mode (stub, live, research)")
    parser.add_argument("--enrichment-mode", type=str, choices=["two_stage", "stub", "live"], default=None, help="Enrichment adapter mode (two_stage, stub, live)")
    parser.add_argument("--domain", type=str, help="Single target company domain for one-off testing (e.g. cyber-shield.io)")
    parser.add_argument("--batch", type=str, help="Path to text file containing target domains (one per line)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Enforce dry run staging (default: True)")
    parser.add_argument("--confirm-live", action="store_true", default=False, help="Explicit confirmation required for live dispatch")
    parser.add_argument("--auto-approve", action="store_true", default=False, help="Automatically approve drafts at manual review checkpoint")
    args = parser.parse_args()

    # Hard safety rule: live sends must never be auto-approved
    if args.confirm_live and args.auto_approve:
        sys.stderr.write("Error: --confirm-live cannot be combined with --auto-approve. Live sends require manual review and cannot be auto-approved.\n")
        sys.exit(1)

    # Enforce safety defaults in environment
    if not args.dry_run:
        os.environ["DRY_RUN"] = "false"
    if args.confirm_live:
        os.environ["CONFIRM_LIVE"] = "true"
    if args.auto_approve:
        os.environ["AUTO_APPROVE"] = "true"
    if args.discovery_mode:
        os.environ["DISCOVERY_MODE"] = args.discovery_mode
    if args.enrichment_mode:
        os.environ["ENRICHMENT_MODE"] = args.enrichment_mode

    company_size = args.company_size or os.getenv("COMPANY_SIZE", "any")

    print_runtime_banner(dry_run=args.dry_run, confirm_live=args.confirm_live, auto_approve=args.auto_approve, company_size=company_size)

    resume_context = load_resume_context()

    # Mode 1: Automated Discovery
    if args.discover is not None:
        if args.discover <= 0:
            print("Error: --discover count must be greater than 0.")
            sys.exit(1)
        try:
            run_discovered_flow(
                target_count=args.discover,
                company_size=company_size,
                resume_context=resume_context,
                auto_approve=args.auto_approve,
                max_attempts=args.max_attempts
            )
        except DailyQuotaExhaustedError:
            sys.exit(1)
        except RuntimeError as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.exit(1)
        return

    # Mode 2: Targeted Manual Domains or Batch
    domains = []
    if args.domain:
        domains.append(args.domain)
    elif args.batch:
        p = Path(args.batch)
        if not p.exists():
            print(f"Error: Batch file {args.batch} not found.")
            sys.exit(1)
        domains = [line.strip() for line in p.read_text().splitlines() if line.strip() and not line.startswith("#")]
    else:
        # Default sample run covering all three personas
        domains = [
            "apex-vault-fintech.io",
            "hyperion-inference-labs.io",
            "nexus-talent-partners.co"
        ]

    # Check volume caps for manual/batch domains
    cap_info = check_volume_caps()
    effective_allowance = cap_info["effective_allowance"]
    if effective_allowance <= 0:
        print(f"\n🚫 [VOLUME CAP EXCEEDED] Cannot process targets.")
        print(f"   • Daily Cap: {cap_info['sends_today']}/{cap_info['max_day']} used (0 remaining)")
        print(f"   • Weekly Cap: {cap_info['sends_week']}/{cap_info['max_week']} used (0 remaining)")
        print(f"   • Skipped all {len(domains)} target(s) to enforce volume invariants.")
        return

    if len(domains) > effective_allowance:
        skipped_count = len(domains) - effective_allowance
        print(f"\n⚠️  [VOLUME CAP THROTTLED] {len(domains)} targets provided, but remaining allowance is {effective_allowance}.")
        print(f"   • Daily Cap: {cap_info['sends_today']}/{cap_info['max_day']} used ({cap_info['remaining_day']} remaining)")
        print(f"   • Weekly Cap: {cap_info['sends_week']}/{cap_info['max_week']} used ({cap_info['remaining_week']} remaining)")
        print(f"   • Processing first {effective_allowance} and skipping remaining {skipped_count}.")
        domains = domains[:effective_allowance]

    delay_ms = int(os.getenv("ENRICHMENT_DELAY_MS", "0"))
    try:
        for idx, d in enumerate(domains):
            if idx > 0 and delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
            run_single_domain(d, resume_context, auto_approve=args.auto_approve)
    except DailyQuotaExhaustedError:
        sys.exit(1)

if __name__ == "__main__":
    main()
