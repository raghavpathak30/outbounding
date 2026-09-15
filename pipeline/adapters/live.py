"""
Live adapter implementations for production services (Apollo, PhantomBuster, Hunter, Gemini, Instantly/Lemlist).
Includes internal fallback chains, pattern verification, and strict dry-run guards.
"""
import os
import re
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import requests
from pipeline.adapters.base import EnrichmentAdapter, DraftingAdapter, DeliveryAdapter, DiscoveryAdapter
from pipeline.adapters.research import ResearchDiscoveryAdapter
from pipeline.config import (
    GEMINI_DRAFTING_MODEL,
    get_drafting_model,
    execute_with_quota_retry,
    DailyQuotaExhaustedError,
    DAILY_QUOTA_RESET_MESSAGE,
)

logger = logging.getLogger("pipeline.adapters.live")

class LiveEnrichmentAdapter(EnrichmentAdapter):
    """
    Production Enrichment Adapter with internal fallback cascade:
    1. Apollo.io Search API
    2. PhantomBuster webhook/API
    3. Hunter.io domain search + pattern generation WITH verification
    """
    
    def __init__(self):
        self.apollo_key = os.getenv("APOLLO_API_KEY", "")
        self.phantombuster_key = os.getenv("PHANTOMBUSTER_API_KEY", "")
        self.hunter_key = os.getenv("HUNTER_API_KEY", "")

    def enrich(self, domain: str) -> Dict[str, Any]:
        # 1. Apollo.io attempt
        result = self._try_apollo(domain)
        if result and result.get("contact_email"):
            return result

        # 2. PhantomBuster fallback attempt
        result = self._try_phantombuster(domain)
        if result and result.get("contact_email"):
            return result

        # 3. Hunter.io pattern match + verification fallback
        result = self._try_hunter_pattern(domain)
        if result and result.get("contact_email"):
            return result

        return {"contact_name": None, "contact_email": None, "contact_role": None, "company_context": None}

    def _parse_org_context(self, org: Dict[str, Any], domain: str) -> Optional[Dict[str, Any]]:
        """
        Parses Apollo organization metadata into standard company_context schema
        (headline, signal, tech_stack) expected by drafting personas.
        """
        if not org or not isinstance(org, dict):
            return None

        name = org.get("name") or domain
        industry = org.get("industry")
        short_desc = org.get("short_description") or org.get("seo_description")

        headline = short_desc or (f"{name} operating in {industry}" if industry else f"Technology company at {domain}")

        # Construct grounded signal from real funding, industry, keywords
        signals = []
        if org.get("total_funding_printed"):
            signals.append(f"Total funding: {org.get('total_funding_printed')}")
        elif org.get("latest_funding_round_date"):
            signals.append(f"Latest funding round: {org.get('latest_funding_round_date')}")
        if industry:
            signals.append(f"Industry: {industry}")
        keywords = org.get("keywords")
        if keywords and isinstance(keywords, list):
            signals.append("Focus areas: " + ", ".join(keywords[:5]))

        signal = "; ".join(signals) if signals else (short_desc or f"Scaling technical operations at {domain}")

        tech_names = org.get("technology_names") or org.get("technologies") or []
        tech_stack = ", ".join(tech_names[:8]) if isinstance(tech_names, list) else ""

        return {
            "headline": headline,
            "signal": signal,
            "tech_stack": tech_stack
        }

    def _fetch_company_context(self, domain: str) -> Optional[Dict[str, Any]]:
        """
        Queries Apollo.io organization enrichment API to fetch company context signal.
        Degrades gracefully if key is missing or call fails.
        """
        if not self.apollo_key:
            return None
        try:
            url = "https://api.apollo.io/v1/organizations/enrich"
            headers = {
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": self.apollo_key
            }
            payload = {"api_key": self.apollo_key, "domain": domain}
            resp = requests.post(url, json=payload, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                org = data.get("organization") or {}
                if org:
                    return self._parse_org_context(org, domain)
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Apollo organization enrich API error for {domain}: {e}")
        return None

    def _try_apollo(self, domain: str) -> Optional[Dict[str, Any]]:
        if not self.apollo_key:
            return None
        try:
            url = "https://api.apollo.io/v1/people/match"
            headers = {
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": self.apollo_key
            }
            payload = {"api_key": self.apollo_key, "domain": domain}
            resp = requests.post(url, json=payload, headers=headers, timeout=10)

            # Explicitly handle Apollo error modes
            if resp.status_code == 429:
                logger.warning(f"Apollo API rate limit (429) encountered for {domain}. Gracefully falling through to fallback.")
                return None
            elif resp.status_code in [401, 403]:
                logger.warning(f"Apollo API authentication failure ({resp.status_code}) for {domain}. Check APOLLO_API_KEY. Gracefully falling through to fallback.")
                return None
            elif resp.status_code != 200:
                logger.warning(f"Apollo API returned unexpected status {resp.status_code} for {domain}. Falling through to fallback.")
                return None

            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError):
                logger.warning(f"Apollo API returned malformed JSON response for {domain}. Falling through.")
                return None

            if not isinstance(data, dict):
                logger.warning(f"Apollo API returned non-dict response for {domain}. Falling through.")
                return None

            person = data.get("person") or {}
            email = person.get("email")
            if not email or "@" not in email:
                logger.info(f"Apollo API returned no person match or email for {domain}. Falling through.")
                return None

            name = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip() or person.get("name") or None
            role = person.get("title")

            # Extract company context from organization data if present
            org = person.get("organization") or data.get("organization") or {}
            company_context = self._parse_org_context(org, domain) if org else None

            return {
                "contact_name": name,
                "contact_email": email,
                "contact_role": role,
                "company_context": company_context
            }
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Apollo API request error for {domain}: {e}. Falling through.")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error in Apollo enrichment for {domain}: {e}. Falling through.")
            return None

    def _try_phantombuster(self, domain: str) -> Optional[Dict[str, Any]]:
        if not self.phantombuster_key:
            return None
        try:
            url = "https://api.phantombuster.com/api/v2/agents/launch"
            headers = {
                "X-Phantombuster-Key": self.phantombuster_key,
                "Content-Type": "application/json"
            }
            payload = {"argument": {"domain": domain}}
            resp = requests.post(url, json=payload, headers=headers, timeout=10)

            # Explicitly handle PhantomBuster error modes
            if resp.status_code == 429:
                logger.warning(f"PhantomBuster API rate limit (429) encountered for {domain}. Falling through to Hunter fallback.")
                return None
            elif resp.status_code in [401, 403]:
                logger.warning(f"PhantomBuster API authentication failure ({resp.status_code}) for {domain}. Check PHANTOMBUSTER_API_KEY. Falling through.")
                return None
            elif resp.status_code != 200:
                logger.warning(f"PhantomBuster API returned unexpected status {resp.status_code} for {domain}. Falling through.")
                return None

            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError):
                logger.warning(f"PhantomBuster API returned malformed JSON response for {domain}. Falling through.")
                return None

            if not isinstance(data, dict):
                logger.warning(f"PhantomBuster API returned non-dict response for {domain}. Falling through.")
                return None

            result_obj = data.get("output") or data.get("container", {}).get("output") or {}
            email = result_obj.get("email")
            if not email or "@" not in email:
                logger.info(f"PhantomBuster API returned no email for {domain}. Falling through.")
                return None

            return {
                "contact_name": result_obj.get("name"),
                "contact_email": email,
                "contact_role": result_obj.get("role") or result_obj.get("title")
            }
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"PhantomBuster API request error for {domain}: {e}. Falling through.")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error in PhantomBuster enrichment for {domain}: {e}. Falling through.")
            return None

    def _verify_email(self, email: str) -> str:
        """
        Calls Hunter's email verifier endpoint (/v2/email-verifier).
        Returns verification status: 'valid', 'invalid', 'accept_all', or 'unknown'.
        """
        if not email or "@" not in email:
            return "invalid"
        if not self.hunter_key:
            logger.warning("Hunter API key not configured; cannot verify email.")
            return "unknown"
        try:
            url = f"https://api.hunter.io/v2/email-verifier?email={email}&api_key={self.hunter_key}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                result = resp.json().get("data", {})
                status = result.get("status", "unknown")
                return status if status in ["valid", "invalid", "accept_all", "unknown"] else "unknown"
            else:
                logger.warning(f"Hunter email verification returned HTTP {resp.status_code} for {email}")
                return "unknown"
        except requests.RequestException as e:
            logger.warning(f"Hunter verification check error for {email}: {e}")
            return "unknown"

    def _verify_email_hunter(self, email: str) -> bool:
        """Strict verification helper: only 'valid' is accepted."""
        return self._verify_email(email) == "valid"

    def _try_hunter_pattern(self, domain: str) -> Optional[Dict[str, Optional[str]]]:
        if not self.hunter_key:
            return None
        try:
            # Domain search to find pattern and representative contact
            url = f"https://api.hunter.io/v2/domain-search?domain={domain}&api_key={self.hunter_key}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                emails = data.get("emails", [])
                if emails:
                    top_contact = emails[0]
                    candidate_email = top_contact.get("value")
                    # Strict verification gate: pattern-guessed email must pass verification (status == 'valid')
                    # Treat accept_all, unknown, and invalid as NOT valid
                    verification_status = self._verify_email(candidate_email)
                    if verification_status == "valid":
                        return {
                            "contact_name": f"{top_contact.get('first_name', '')} {top_contact.get('last_name', '')}".strip() or None,
                            "contact_email": candidate_email,
                            "contact_role": top_contact.get("position")
                        }
                    else:
                        logger.warning(f"Hunter candidate email {candidate_email} rejected by verification gate (status: {verification_status}).")
        except requests.RequestException as e:
            logger.warning(f"Hunter API error for {domain}: {e}")
        return None


class LiveDraftingAdapter(DraftingAdapter):
    """
    Production Drafting Adapter utilizing ChatGoogleGenerativeAI with latest Gemini models
    and an intelligent offline synthesis fallback.
    """
    
    def __init__(self, model_name: Optional[str] = None):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model_name = model_name or get_drafting_model()

    def build_prompt(
        self,
        role: Optional[str],
        domain: str,
        resume_context: Dict[str, Any],
        contact_name: Optional[str],
        company_context: Optional[Dict[str, Any]] = None
    ) -> tuple[str, list, str]:
        """
        Constructs the structured prompt, persona strategy, and extracts relevant bullets
        for the Gemini model.
        Returns: (system_instruction, bullets, persona_category)
        """
        role_str = role or "Engineering Lead"
        role_lower = role_str.lower()
        
        is_ai = any(w in role_lower for w in ["ai", "ml", "machine learning", "data science", "llm", "deep learning", "inference", "neural"])
        is_sec = any(w in role_lower for w in ["security", "ciso", "secops", "crypt", "cyber", "pentest", "vulnerability"]) or ("infra" in role_lower and not is_ai)

        if is_ai:
            persona_category = "ai_machine_learning"
            persona_focus = (
                "Highlight end-to-end application architecture, low-latency Gemini API integrations "
                "built via Google AI Studio, and schema-constrained RAG systems."
            )
            bullets = resume_context.get("ai_machine_learning", {}).get("highlights", [])
        elif is_sec:
            persona_category = "security_infrastructure"
            persona_focus = (
                "Emphasize hands-on cybersecurity work implementing timing side-channel attacks, "
                "vulnerability research on DSS modular arithmetic, and CKKS homomorphic encryption."
            )
            bullets = resume_context.get("security_infrastructure", {}).get("highlights", [])
        else:
            persona_category = "hr_talent_acquisition"
            persona_focus = (
                "Pivot to an ATS-optimized, high-level impact summary emphasizing B.Tech CSE at LNMIIT, "
                "National Grand Finalist at IIT Hyderabad, and rapid cross-functional execution."
            )
            bullets = resume_context.get("hr_talent_acquisition", {}).get("highlights", [])

        portfolio_url = resume_context.get("personal", {}).get("portfolio", "https://raghavpathak.dev")

        # Handle groundable company_context signal
        if company_context:
            signal_text = company_context.get("signal") or company_context.get("headline") or str(company_context)
            tech_stack = f" | Tech Stack: {company_context['tech_stack']}" if isinstance(company_context, dict) and company_context.get("tech_stack") else ""
            context_block = f"Verified Target Company Signal: {signal_text}{tech_stack}\n"
            opening_rule = (
                f"   - GROUNDED OPENING REQUIRED: You MUST ground your opening line directly in the verified Target Company Signal provided above (e.g. referencing '{signal_text}').\n"
                f"   - STRICT PROHIBITION: NEVER extrapolate, fabricate, or claim familiarity beyond the exact verified Target Company Signal provided.\n"
            )
        else:
            context_block = "Verified Target Company Signal: None (No verified company signal available)\n"
            opening_rule = (
                f"   - STRICT PROHIBITION: NEVER claim or imply prior familiarity with the company's specific work, team, engineering updates, or public posts (e.g., NEVER say 'Saw your team\'s work on...', 'Following your engineering updates...', 'I noticed your focus on...') because no company signal is available.\n"
                f"   - Ground the opening line strictly in what is known and true: the recipient's role, the target domain/industry, or a direct statement of why you are reaching out.\n"
                f"   - Examples of honest, grounded openers:\n"
                f"     * Direct technical intent: 'I\'m reaching out directly because I build high-performance cryptography and security systems...'\n"
                f"     * Role/domain context: 'Reaching out to connect with engineering leadership at {domain} regarding systems security...'\n"
                f"     * Direct project relevance: 'I recently built an applied ML pipeline and wanted to get in touch with your infrastructure team...'\n"
            )

        system_instruction = (
            f"You are drafting a natural, highly personalized cold outreach email from Raghav Pathak to {contact_name or 'a technical leader'}.\n"
            f"Context: Recipient is {role_str} at {domain}.\n"
            f"{context_block}"
            f"Persona Strategy: {persona_focus}\n"
            f"Portfolio URL: {portfolio_url}\n"
            f"Raw Technical Highlights: {json.dumps(bullets)}\n\n"
            f"CRITICAL WRITING REQUIREMENTS:\n"
            f"1. Subject Line: Start your output with 'Subject: <custom, contextual subject line tailored specifically to {domain} and persona>' followed by two newlines.\n"
            f"2. Grounded Opening (STRICT ANTI-FABRICATION RULE):\n"
            f"{opening_rule}"
            f"   - DO NOT restate their full job title back to them (e.g., never say 'Given your role as Chief Information Security Officer & VP Infrastructure...').\n"
            f"   - NEVER use generic filler like 'I hope this email finds you well'.\n"
            f"3. Spoken, Conversational Tone: Convert resume bullets into 1 or 2 natural spoken sentences. Explain it like talking to a smart engineer over coffee, not reciting CV bullets.\n"
            f"4. Length Cap: Cap total body at ~80-100 words. Keep it concise: one line of context, one or two concrete highlights, one portfolio link line, one short ask.\n"
            f"5. Portfolio Link: Always include the portfolio link naturally in the body (e.g., 'More on my architecture and code here: {portfolio_url}') as the place to go deep.\n"
            f"6. Low-Friction Ask: End with a specific, low-friction ask that invites a one-line reply (e.g., 'Worth a quick 10-minute chat next week?' or 'Happy to send my resume over if helpful.')."
        )
        return system_instruction, bullets, persona_category

    def draft(
        self,
        role: Optional[str],
        domain: str,
        resume_context: Dict[str, Any],
        contact_name: Optional[str],
        company_context: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Any]] = None
    ) -> str:
        role_str = role or "Engineering Lead"
        system_instruction, bullets, persona_category = self.build_prompt(
            role=role,
            domain=domain,
            resume_context=resume_context,
            contact_name=contact_name,
            company_context=company_context
        )

        api_key = self.api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")

        # If API key is configured, invoke Gemini with proactive pacing and quota retry
        if api_key:
            def _call_gemini():
                if tools:
                    # Tool-bound calls refactored to Chat.send_message to eliminate AFC warning
                    from google import genai
                    from google.genai import types

                    client = genai.Client(api_key=api_key)
                    chat = client.chats.create(
                        model=self.model_name,
                        config=types.GenerateContentConfig(
                            tools=tools,
                            temperature=0.3,
                        )
                    )
                    response = chat.send_message(system_instruction)
                    if response and hasattr(response, "text") and response.text:
                        return response.text.strip()
                    return ""
                else:
                    from langchain_google_genai import ChatGoogleGenerativeAI
                    llm = ChatGoogleGenerativeAI(
                        model=self.model_name,
                        google_api_key=api_key,
                        temperature=0.3
                    )
                    response = llm.invoke([{"role": "user", "content": system_instruction}])
                    if response and response.content:
                        return str(response.content).strip()
                    return ""

            try:
                res = execute_with_quota_retry(_call_gemini, adapter_name="LiveDraftingAdapter")
                if res:
                    return res
            except DailyQuotaExhaustedError:
                logger.warning("Gemini daily quota exhausted during drafting. Using structured local fallback.")
            except Exception as e:
                logger.warning(f"Live Gemini invocation failed ({e}), using structured local fallback.")

        # Offline synthesis fallback matching the exact conversational, short coffee-chat style
        portfolio_url = resume_context.get("personal", {}).get("portfolio", "https://raghavpathak.dev")
        greeting = f"Hi {contact_name}," if contact_name else "Hi there,"

        if persona_category == "security_infrastructure":
            subject = f"Encrypted transaction compute & security — {domain}"
            if company_context and isinstance(company_context, dict) and "Series B" in company_context.get("signal", ""):
                opener = f"Saw {domain}'s announcement regarding your Series B expansion to build privacy-preserving encrypted settlement architecture."
            elif company_context and isinstance(company_context, dict) and company_context.get("signal"):
                opener = f"Noted {domain}'s recent focus on {company_context['signal']}."
            else:
                opener = f"I'm reaching out directly given your infrastructure security leadership at {domain}."

            body = (
                f"Subject: {subject}\n\n"
                f"{greeting}\n\n"
                f"{opener} "
                f"I'm an applied security engineer who recently built an encrypted fraud-scoring service using CKKS homomorphic encryption that reached 98% accuracy over live bank transaction data without server-side decryption, alongside vulnerability work analyzing timing side-channels in DSS modular arithmetic.\n\n"
                f"More details on the architecture and benchmarks here: {portfolio_url}\n\n"
                f"Worth a quick 10-minute chat next week?\n\n"
                f"Best,\nRaghav Pathak"
            )
        elif persona_category == "ai_machine_learning":
            subject = f"Low-latency Gemini orchestration & agent systems at {domain}"
            if company_context and isinstance(company_context, dict) and "speculative decoding" in company_context.get("signal", ""):
                opener = f"Saw {domain}'s open-source release of high-throughput speculative decoding for low-latency LLM serving."
            elif company_context and isinstance(company_context, dict) and company_context.get("signal"):
                opener = f"Noted {domain}'s engineering updates around {company_context['signal']}."
            else:
                opener = f"I'm reaching out directly to connect with engineering leadership in AI systems and infrastructure at {domain}."

            body = (
                f"Subject: {subject}\n\n"
                f"{greeting}\n\n"
                f"{opener} "
                f"I've been building low-latency LLM agent pipelines using Google AI Studio and Gemini 2.5, including a solo-built chargeback responder for the Razorpay hackathon where I placed the model directly inside the decision loop rather than treating it as a text wrapper.\n\n"
                f"I've shared system breakdowns and open-source code here: {portfolio_url}\n\n"
                f"Happy to send my resume over if useful?\n\n"
                f"Best,\nRaghav Pathak"
            )
        else:
            subject = f"Systems & AI Engineering — Raghav Pathak for {domain}"
            if company_context and isinstance(company_context, dict) and ("autonomous" in company_context.get("signal", "") or "technical recruiting" in company_context.get("headline", "")):
                opener = f"Reaching out because {domain} specializes in technical talent placement for founding engineers in autonomous systems and AI infrastructure."
            elif company_context and isinstance(company_context, dict) and company_context.get("signal"):
                opener = f"Reaching out because {domain} focuses on {company_context['signal']}."
            else:
                opener = f"I'm reaching out directly regarding technical engineering opportunities at {domain}."

            body = (
                f"Subject: {subject}\n\n"
                f"{greeting}\n\n"
                f"{opener} "
                f"I'm a final-year CS undergrad at LNMIIT focusing on systems security and applied AI. Recently, our team reached the national grand finale at IIT Hyderabad for banking threat detection, and I frequently ship standalone AI and cryptography services with tight SLAs.\n\n"
                f"Portfolio and technical writeups are available at: {portfolio_url}\n\n"
                f"Open to a brief conversation if there's potential alignment?\n\n"
                f"Best,\nRaghav Pathak"
            )

        return body


def confirm_recipient_count(recipients: List[Dict[str, Any]]) -> bool:
    """
    Deliberate extra friction point before firing live sends:
    Prints a summary (recipient count, list of recipient emails, domains)
    and requires typing the literal recipient count as confirmation before proceeding.
    Returns True if confirmed, False if rejected or mismatched.
    """
    count = len(recipients)
    if count == 0:
        return True

    print("\n" + "=" * 72)
    print(" ⚠️  CRITICAL: LIVE SEND EXTRA CONFIRMATION GATE")
    print("=" * 72)
    print(f" Summary: About to dispatch LIVE emails to {count} recipient{'s' if count != 1 else ''}:")
    for idx, r in enumerate(recipients, 1):
        if isinstance(r, dict):
            email = r.get("email") or (r.get("recipient", {}).get("email") if isinstance(r.get("recipient"), dict) else None)
            domain = r.get("domain") or ""
            name = r.get("name") or (r.get("recipient", {}).get("name") if isinstance(r.get("recipient"), dict) else "")
        else:
            email = str(r)
            domain = ""
            name = ""
        print(f"   {idx}. {name} <{email}> (domain: {domain})")
    print("=" * 72)

    prompt_msg = f"Type {count} to confirm sending to {'these ' + str(count) + ' people' if count != 1 else 'this 1 person'}: "
    try:
        user_input = input(prompt_msg).strip()
    except EOFError:
        user_input = ""

    if user_input == str(count):
        print(" ✓ Recipient count verified. Proceeding with live dispatch.\n")
        return True
    else:
        print(f" ✗ Confirmation failed. Expected '{count}', received '{user_input}'. Live dispatch aborted.\n")
        return False


class LiveDeliveryAdapter(DeliveryAdapter):
    """
    Live Delivery Adapter interfacing with Instantly.ai / Lemlist webhook APIs.
    HARDCODED SAFETY: Live send path only executes when ALL 4 conditions are met simultaneously:
      1. DELIVERY_MODE == "live"
      2. DRY_RUN is false
      3. --confirm-live was passed
      4. review_status == "approved"
    Missing any one of these falls back to staging-only behavior identical to today,
    logging clearly which condition was not met.

    Also enforces:
      - First-real-send extra confirmation (recipient count friction prompt)
      - Send-rate pacing via DELIVERY_DELAY_MS
    """
    _first_send_confirmed: bool = False
    _last_send_time: float = 0.0

    @classmethod
    def reset_safety_state(cls):
        """Reset confirmation and pacing state for tests or fresh runs."""
        cls._first_send_confirmed = False
        cls._last_send_time = 0.0

    @classmethod
    def confirm_batch(cls, recipients: List[Dict[str, Any]]) -> bool:
        """Explicitly confirm a batch of recipients upfront."""
        confirmed = confirm_recipient_count(recipients)
        if confirmed:
            cls._first_send_confirmed = True
        return confirmed

    def __init__(self):
        self.instantly_key = os.getenv("INSTANTLY_API_KEY", "")
        self.lemlist_key = os.getenv("LEMLIST_API_KEY", "")
        self.provider = os.getenv("DELIVERY_PROVIDER", "instantly").lower()

    def deliver(
        self,
        payload: Dict[str, Any],
        dry_run: bool = True,
        confirm_live: bool = False,
        review_status: Optional[str] = None
    ) -> Dict[str, Any]:
        domain = payload.get("domain", "")

        # 1. Evaluate all 4 mandatory live dispatch safety conditions
        delivery_mode = os.getenv("DELIVERY_MODE", "stub").lower()
        is_dry_run = dry_run or (os.getenv("DRY_RUN", "true").lower() in ["true", "1", "yes"])
        is_confirm_live = confirm_live or (os.getenv("CONFIRM_LIVE", "false").lower() in ["true", "1", "yes"])
        current_review_status = review_status or payload.get("review_status")

        unmet = []
        if delivery_mode != "live":
            unmet.append(f"DELIVERY_MODE is '{delivery_mode}' (expected 'live')")
        if is_dry_run:
            unmet.append("DRY_RUN is active (expected false)")
        if not is_confirm_live:
            unmet.append("--confirm-live flag was not passed (expected true)")
        if current_review_status != "approved":
            unmet.append(f"review_status is '{current_review_status}' (expected 'approved')")

        # If ANY condition is not met, fall back to staging-only behavior identical to today
        if unmet:
            unmet_str = "; ".join(unmet)
            logger.info(f"Live delivery blocked: {unmet_str}. Falling back to staging-only behavior.")
            staged_dir = Path("staged_deliveries")
            staged_dir.mkdir(parents=True, exist_ok=True)
            domain_slug = domain.replace(".", "_") if domain else "unknown"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = staged_dir / f"live_staged_{domain_slug}_{timestamp}.json"

            record = {
                "mode": "live_staged_safe",
                "dry_run": is_dry_run,
                "confirm_live": is_confirm_live,
                "review_status": current_review_status,
                "unmet_conditions": unmet,
                "staged_at": datetime.now().isoformat(),
                "payload": payload,
                "notice": f"Outbound HTTP blocked by safety gates: {unmet_str}."
            }
            filename.write_text(json.dumps(record, indent=2), encoding="utf-8")
            return {
                "status": "staged",
                "file": str(filename),
                "notice": f"Safely staged to disk; no outbound network call executed ({unmet_str})."
            }

        # 2. First-real-send extra confirmation gate
        if not LiveDeliveryAdapter._first_send_confirmed:
            recip = {
                "email": payload.get("recipient", {}).get("email") if isinstance(payload.get("recipient"), dict) else payload.get("recipient"),
                "name": payload.get("recipient", {}).get("name") if isinstance(payload.get("recipient"), dict) else "",
                "domain": domain
            }
            if not confirm_recipient_count([recip]):
                err_msg = "Live dispatch aborted: recipient count confirmation rejected by user"
                logger.warning(f"{err_msg} for {domain}.")
                return {
                    "status": "failed",
                    "error": err_msg
                }
            LiveDeliveryAdapter._first_send_confirmed = True

        # 3. Send-rate pacing: DELIVERY_DELAY_MS
        delivery_delay_ms = int(os.getenv("DELIVERY_DELAY_MS", "0"))
        if delivery_delay_ms > 0 and LiveDeliveryAdapter._last_send_time > 0:
            elapsed_ms = (time.time() - LiveDeliveryAdapter._last_send_time) * 1000.0
            if elapsed_ms < delivery_delay_ms:
                sleep_sec = (delivery_delay_ms - elapsed_ms) / 1000.0
                logger.info(f"Pacing live delivery: sleeping {sleep_sec:.3f}s (DELIVERY_DELAY_MS={delivery_delay_ms})")
                time.sleep(sleep_sec)

        # 4. Dispatch live webhook POST
        provider = os.getenv("DELIVERY_PROVIDER", self.provider).lower()
        if provider == "lemlist":
            webhook_url = os.getenv("LEMLIST_WEBHOOK_URL", "https://api.lemlist.com/api/leads")
            key = self.lemlist_key or os.getenv("LEMLIST_API_KEY", "")
            if not key:
                err_msg = "Lemlist dispatch failed: LEMLIST_API_KEY not configured"
                logger.error(f"{err_msg} for {domain}.")
                return {"status": "failed", "error": err_msg}
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}"
            }
            post_body = payload
        else:
            # Default: Instantly.ai
            webhook_url = os.getenv("INSTANTLY_WEBHOOK_URL", "https://api.instantly.ai/api/v1/lead/add")
            key = self.instantly_key or os.getenv("INSTANTLY_API_KEY", "")
            if not key:
                err_msg = "Instantly dispatch failed: INSTANTLY_API_KEY not configured"
                logger.error(f"{err_msg} for {domain}.")
                return {"status": "failed", "error": err_msg}
            headers = {
                "Content-Type": "application/json"
            }
            recip_obj = payload.get("recipient", {})
            recip_name = recip_obj.get("name", "") if isinstance(recip_obj, dict) else ""
            name_parts = recip_name.split() if recip_name else []
            post_body = {
                "api_key": key,
                "campaign_id": payload.get("campaign_id", "outbound_tech_lead_sequence_v1"),
                "email": recip_obj.get("email") if isinstance(recip_obj, dict) else payload.get("recipient"),
                "first_name": name_parts[0] if name_parts else "",
                "last_name": " ".join(name_parts[1:]) if len(name_parts) > 1 else "",
                "company_name": domain,
                "custom_variables": payload.get("custom_variables", {}),
                "email_subject": payload.get("email_subject", ""),
                "email_body": payload.get("email_body", "")
            }

        try:
            resp = requests.post(webhook_url, json=post_body, headers=headers, timeout=10)
        except requests.exceptions.Timeout as e:
            err_msg = f"Network timeout during live dispatch: {e}"
            logger.error(f"{err_msg} for {domain}")
            return {"status": "failed", "error": err_msg}
        except requests.RequestException as e:
            err_msg = f"Network error during live dispatch: {e}"
            logger.error(f"{err_msg} for {domain}")
            return {"status": "failed", "error": err_msg}
        except Exception as e:
            err_msg = f"Unexpected error during live dispatch: {e}"
            logger.error(f"{err_msg} for {domain}")
            return {"status": "failed", "error": err_msg}
        finally:
            LiveDeliveryAdapter._last_send_time = time.time()

        # Handle HTTP status codes
        if resp.status_code == 429:
            err_msg = f"Rate limit (429) exceeded: {resp.text}"
            logger.error(f"Live dispatch rate limit exceeded for {domain}: {resp.text}")
            return {"status": "failed", "error": err_msg}
        elif resp.status_code in [401, 403]:
            err_msg = f"Authentication failure ({resp.status_code}): {resp.text}"
            logger.error(f"Live dispatch auth failure ({resp.status_code}) for {domain}. Check API key.")
            return {"status": "failed", "error": err_msg}
        elif resp.status_code in [400, 422]:
            err_msg = f"Payload rejected ({resp.status_code}): {resp.text}"
            logger.error(f"Live dispatch payload rejected ({resp.status_code}) for {domain}: {resp.text}")
            return {"status": "failed", "error": err_msg}
        elif resp.status_code < 200 or resp.status_code >= 300:
            err_msg = f"HTTP {resp.status_code}: {resp.text}"
            logger.error(f"Live dispatch HTTP error ({resp.status_code}) for {domain}: {resp.text}")
            return {"status": "failed", "error": err_msg}

        logger.info(f"Live dispatch succeeded for {domain} (HTTP {resp.status_code})")
        return {
            "status": "sent",
            "http_status": resp.status_code,
            "response": resp.text
        }


class LiveDiscoveryAdapter(DiscoveryAdapter):
    """
    Live discovery adapter querying Apollo's organization search endpoint:
    https://api.apollo.io/v1/organizations/search
    Filtered by technical profile tags: applied cryptography, cybersecurity, fintech fraud detection, AI/LLM infrastructure, AI security.
    Supports employee count filtering based on company_size ('small', 'established', 'any').
    """
    TARGET_KEYWORDS = [
        "applied cryptography",
        "cybersecurity",
        "fintech fraud detection",
        "AI infrastructure",
        "AI security"
    ]

    def __init__(self):
        self.apollo_key = os.getenv("APOLLO_API_KEY", "")

    def discover(self, limit: int = 10, company_size: str = "any") -> List[Dict[str, Any]]:
        if not self.apollo_key:
            logger.warning("APOLLO_API_KEY not set; live discovery cannot execute.")
            return []

        url = "https://api.apollo.io/v1/organizations/search"
        headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.apollo_key,
        }

        size_filter = (company_size or "any").lower().strip()
        employee_ranges: List[str] = []
        if size_filter == "small":
            employee_ranges = ["1,10"]
        elif size_filter == "established":
            employee_ranges = ["21,50", "51,100", "101,250", "251,500", "501,1000", "1001,5000", "5001,10000", "10001"]

        payload: Dict[str, Any] = {
            "api_key": self.apollo_key,
            "q_organization_keyword_tags": self.TARGET_KEYWORDS,
            "page": 1,
            "per_page": max(limit * 2, 10),
        }
        if employee_ranges:
            payload["organization_num_employees_ranges"] = employee_ranges

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout querying Apollo organization search: {e}")
            return []
        except requests.RequestException as e:
            logger.error(f"Network error querying Apollo organization search: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error querying Apollo organization search: {e}")
            return []

        if resp.status_code == 429:
            logger.error(f"Apollo organization search rate limited (429): {resp.text}")
            return []
        elif resp.status_code in [401, 403]:
            logger.error(f"Apollo organization search auth failure ({resp.status_code}): {resp.text}")
            return []
        elif resp.status_code < 200 or resp.status_code >= 300:
            logger.error(f"Apollo organization search HTTP error ({resp.status_code}): {resp.text}")
            return []

        try:
            data = resp.json()
        except Exception as e:
            logger.error(f"Failed to decode Apollo organization search JSON: {e}")
            return []

        raw_orgs = data.get("organizations", [])
        candidates = []

        for org in raw_orgs:
            if not isinstance(org, dict):
                continue

            raw_domain = org.get("primary_domain") or ""
            if not raw_domain and org.get("website_url"):
                raw_domain = org.get("website_url", "")

            domain = self._clean_domain(raw_domain)
            if not domain:
                continue

            name = org.get("name") or domain
            industry = org.get("industry") or "Technology"
            size = org.get("estimated_num_employees") or 0
            funding = org.get("total_funding_printed") or ""
            tech_names = org.get("technology_names") or org.get("technologies") or []
            tech_stack = ", ".join(tech_names[:8]) if isinstance(tech_names, list) else ""

            short_desc = org.get("short_description") or org.get("seo_description") or ""
            headline = short_desc or f"{name} operating in {industry}"

            signals = []
            if funding:
                signals.append(f"Funding: {funding}")
            if industry:
                signals.append(f"Industry: {industry}")
            if size:
                signals.append(f"{size} employees")
            keywords = org.get("keywords")
            if keywords and isinstance(keywords, list):
                signals.append("Focus areas: " + ", ".join(keywords[:4]))
            signal_str = "; ".join(signals) if signals else headline

            company_context = {
                "headline": headline,
                "signal": signal_str,
                "tech_stack": tech_stack
            }

            candidates.append({
                "domain": domain,
                "company_name": name,
                "industry": industry,
                "size": size,
                "funding": funding,
                "company_context": company_context
            })

            if len(candidates) >= limit:
                break

        return candidates

    @staticmethod
    def _clean_domain(raw: str) -> str:
        d = raw.strip().lower()
        d = re.sub(r"^https?://", "", d)
        d = re.sub(r"^www\.", "", d)
        d = d.split("/")[0].split("?")[0].strip()
        return d

