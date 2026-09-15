"""
Person Research Adapter for discovering real technical leaders (Founder, CTO, VP Eng).
Utilizes Gemini with Google Search Grounding to identify verified leaders without fabrication.
"""
import os
import re
import json
import logging
from typing import Optional, Dict, Any

from pipeline.adapters.base import PersonResearchAdapter
from pipeline.config import (
    get_person_research_model,
    MIN_PERSON_CONFIDENCE,
    execute_with_quota_retry,
    DailyQuotaExhaustedError,
)

logger = logging.getLogger("pipeline.adapters.person_research")

# Blacklist of tokens that indicate generic placeholder or fabricated names
FORBIDDEN_NAME_TOKENS = {
    "alex morgan", "admin", "info", "support", "founder", "co-founder",
    "cto", "hiring", "team", "engineer", "lead", "recruiter", "talent",
    "placeholder", "contact", "anonymous", "null", "none"
}

LEADERSHIP_ROLE_PATTERN = re.compile(
    r"(cto|chief technology officer|founder|co-founder|vp|vice president|head of engineering|director of engineering|founding engineer|chief architect)",
    re.IGNORECASE
)


class GeminiPersonResearchAdapter(PersonResearchAdapter):
    """
    Search-grounded leader discovery adapter using Gemini with Google Search tool.
    Identifies real, current technical leadership for target company domains.
    Enforces strict anti-hallucination validation and negative blacklist filtering.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.api_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
        self.model_name = model_name or get_person_research_model()

    def build_research_prompt(
        self,
        domain: str,
        company_name: Optional[str] = None,
        company_context: Optional[Dict[str, Any]] = None
    ) -> str:
        name_str = company_name or domain
        ctx_str = ""
        if company_context and isinstance(company_context, dict):
            signal = company_context.get("signal") or company_context.get("headline") or ""
            stack = company_context.get("tech_stack") or ""
            ctx_str = f"Target Context: {signal}. Tech Stack: {stack}."

        prompt = (
            f"You are an expert executive talent intelligence agent. Use your Google Search tool to identify the "
            f"current, authentic technical leader or founder at '{name_str}' (primary domain: '{domain}').\n\n"
            f"{ctx_str}\n\n"
            f"MULTI-SOURCE SEARCH STRATEGY:\n"
            f"Execute search queries combining:\n"
            f"1. First-party company web presence: site:{domain} (/about, /team, /leadership, technical blog, or engineering posts)\n"
            f"2. Executive professional profiles: (\"{name_str}\" OR \"{domain}\") (CTO OR \"Chief Technology Officer\" OR Founder OR \"VP of Engineering\" OR \"Head of Engineering\")\n"
            f"3. Technical press & corporate registries: TechCrunch, Crunchbase, GitHub org, or funding releases\n\n"
            f"ROLE HIERARCHY (SELECT EXACTLY ONE BEST CANDIDATE IN THIS ORDER):\n"
            f"1. CTO / Chief Technology Officer\n"
            f"2. Technical Co-Founder / Co-Founder & CTO\n"
            f"3. VP of Engineering / VP Engineering\n"
            f"4. Head of Engineering / Engineering Lead\n"
            f"5. Founder & CEO (especially if the startup is early-stage/small)\n\n"
            f"MANDATORY SEARCH GROUNDING REQUIREMENTS:\n"
            f"1. You MUST verify that this person is currently in this role and associated with {domain}.\n"
            f"2. Reject former employees, advisors, non-technical executives (unless early solo founder), or contractors.\n"
            f"3. Find their real first name, last name, exact current job title, public LinkedIn profile URL or authoritative citation URL.\n"
            f"4. You MUST provide an 'evidence_snippet' quoting the search result evidence that links this person to {domain}.\n"
            f"5. STRICT ANTI-FABRICATION RULE: If you cannot verify a real, currently active technical leader with high confidence from public search results, you MUST set 'found': false. Do NOT guess, do NOT hallucinate, and do NOT provide generic placeholder names.\n\n"
            f"OUTPUT FORMAT REQUIREMENT:\n"
            f"Return ONLY a valid JSON object. Do NOT include markdown code fences, comments, or conversational text.\n"
            f"JSON schema:\n"
            f"{{\n"
            f'  "found": true,\n'
            f'  "first_name": "Firstname",\n'
            f'  "last_name": "Lastname",\n'
            f'  "full_name": "Firstname Lastname",\n'
            f'  "role": "Chief Technology Officer",\n'
            f'  "linkedin_url": "https://www.linkedin.com/in/...",\n'
            f'  "source_url": "https://...",\n'
            f'  "evidence_snippet": "Direct quote or specific factual detail from search confirming current role at company",\n'
            f'  "reasoning": "Brief explanation of grounding evidence",\n'
            f'  "confidence_score": 0.95\n'
            f"}}\n"
            f"If no verified leader is found, return:\n"
            f'{{"found": false, "reason": "no_verified_technical_leader_found", "confidence_score": 0.0}}\n'
        )
        return prompt

    def _query_gemini(self, prompt: str) -> tuple[str, list[dict]]:
        """
        Queries Gemini with Google Search tool and extracts both response text
        and first-party SDK grounding metadata chunks.
        Returns: (response_text, list_of_grounding_sources)
        """
        api_key = self.api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            logger.warning("GEMINI_API_KEY not set; person research cannot query live Gemini.")
            return "", []

        def _call_gemini():
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            chat = client.chats.create(
                model=self.model_name,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.1,
                )
            )
            response = chat.send_message(prompt)
            raw_text = ""
            grounding_sources = []

            if response:
                if hasattr(response, "text") and response.text:
                    raw_text = response.text
                elif response.candidates and response.candidates[0].content:
                    parts = response.candidates[0].content.parts or []
                    raw_text = "".join(getattr(p, "text", "") for p in parts if getattr(p, "text", ""))
                else:
                    raw_text = str(response)

                # Extract SDK-level grounding metadata if present
                try:
                    if response.candidates and response.candidates[0].grounding_metadata:
                        meta = response.candidates[0].grounding_metadata
                        chunks = getattr(meta, "grounding_chunks", None) or []
                        for c in chunks:
                            web = getattr(c, "web", None)
                            if web:
                                grounding_sources.append({
                                    "uri": getattr(web, "uri", ""),
                                    "title": getattr(web, "title", ""),
                                    "domain": getattr(web, "domain", "")
                                })
                except Exception as e:
                    logger.debug(f"Could not parse grounding chunks: {e}")

            return raw_text, grounding_sources

        return execute_with_quota_retry(_call_gemini, adapter_name="GeminiPersonResearchAdapter")

    def _parse_llm_json(self, raw_text: str) -> Optional[Dict[str, Any]]:
        if not raw_text or not raw_text.strip():
            return None
        text = raw_text.strip()
        if "```json" in text:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if m:
                text = m.group(1)
        elif "```" in text:
            m = re.search(r"```\s*(\{.*?\})\s*```", text, re.DOTALL)
            if m:
                text = m.group(1)
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception as e:
                    logger.warning(f"Regex JSON fallback parsing failed in person research: {e}")
        return None

    def validate_leader(
        self,
        data: Dict[str, Any],
        grounding_sources: Optional[list] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Enforces strict anti-hallucination and validation gates on person discovery output.
        Rejects low-confidence, generic, or blacklisted placeholder contacts.
        """
        if not data or not isinstance(data, dict):
            return None

        if not data.get("found", True):
            logger.info(f"Person research returned found=false: {data.get('reason')}")
            return None

        confidence = float(data.get("confidence_score") or 0.0)
        if confidence < MIN_PERSON_CONFIDENCE:
            logger.warning(
                f"Person research candidate rejected: confidence {confidence:.2f} below threshold {MIN_PERSON_CONFIDENCE}"
            )
            return None

        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()
        full_name = (data.get("full_name") or f"{first_name} {last_name}").strip()
        role = (data.get("role") or "").strip()

        # Name completeness check
        if not first_name or not last_name:
            # Attempt to split full_name if first/last were omitted
            parts = full_name.split()
            if len(parts) >= 2:
                first_name, last_name = parts[0], " ".join(parts[1:])
            else:
                logger.warning(f"Person research candidate rejected: incomplete name '{full_name}'")
                return None

        # Sanity check: Name must not contain digits or web symbols
        if any(char.isdigit() or char in "@/<>{};:!#$" for char in full_name):
            logger.warning(f"Person research candidate rejected: invalid characters in name '{full_name}'")
            return None

        # Negative blacklist check (regression defense)
        name_lower = full_name.lower()
        if any(token in name_lower for token in FORBIDDEN_NAME_TOKENS):
            logger.warning(f"Person research candidate rejected by negative blacklist: '{full_name}'")
            return None

        # Leadership role regex check
        if not LEADERSHIP_ROLE_PATTERN.search(role):
            logger.warning(f"Person research candidate rejected: non-leadership role '{role}'")
            return None

        evidence_snippet = data.get("evidence_snippet") or data.get("reasoning")
        source_url = data.get("source_url") or data.get("linkedin_url")
        if not source_url and grounding_sources:
            source_url = grounding_sources[0].get("uri")

        return {
            "first_name": first_name,
            "last_name": last_name,
            "full_name": full_name,
            "role": role,
            "linkedin_url": data.get("linkedin_url"),
            "source_url": source_url,
            "evidence_snippet": evidence_snippet,
            "person_confidence": confidence,
            "grounding_sources": grounding_sources or []
        }

    def find_leader(
        self,
        domain: str,
        company_name: Optional[str] = None,
        company_context: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        prompt = self.build_research_prompt(domain, company_name, company_context)
        try:
            raw_text, grounding_sources = self._query_gemini(prompt)
        except DailyQuotaExhaustedError:
            raise
        except Exception as e:
            logger.error(f"Error querying Gemini for person research on {domain}: {e}")
            return None

        data = self._parse_llm_json(raw_text)
        if not data:
            logger.warning(f"Failed to parse person research response for {domain}")
            return None

        verified = self.validate_leader(data, grounding_sources=grounding_sources)
        if verified:
            logger.info(
                f"Verified leader for {domain}: {verified['full_name']} ({verified['role']}, confidence: {verified['person_confidence']:.2f})"
            )
        return verified


class StubPersonResearchAdapter(PersonResearchAdapter):
    """
    Deterministic stub adapter for zero-network testing.
    Only returns leaders for explicitly defined mock test fixtures.
    Returns None for all arbitrary or unknown domains.
    """

    MOCK_LEADERS = {
        "apex-vault-fintech.io": {
            "first_name": "Devon",
            "last_name": "Sterling",
            "full_name": "Devon Sterling",
            "role": "Chief Information Security Officer & VP Infrastructure",
            "linkedin_url": "https://www.linkedin.com/in/devon-sterling-mock",
            "source_url": "https://apex-vault-fintech.io/leadership",
            "person_confidence": 0.95
        },
        "hyperion-inference-labs.io": {
            "first_name": "Maya",
            "last_name": "Lin",
            "full_name": "Dr. Maya Lin",
            "role": "VP of AI Systems & Low-Latency LLM Infrastructure",
            "linkedin_url": "https://www.linkedin.com/in/maya-lin-mock",
            "source_url": "https://hyperion-inference-labs.io/team",
            "person_confidence": 0.95
        },
        "nexus-talent-partners.co": {
            "first_name": "Julian",
            "last_name": "Rivera",
            "full_name": "Julian Rivera",
            "role": "Director of Technical Talent & Engineering Recruiting",
            "linkedin_url": "https://www.linkedin.com/in/julian-rivera-mock",
            "source_url": "https://nexus-talent-partners.co/about",
            "person_confidence": 0.95
        },
        "cyber-corp.com": {
            "first_name": "Marcus",
            "last_name": "Vance",
            "full_name": "Marcus Vance",
            "role": "Head of Information Security & Infrastructure",
            "linkedin_url": "https://www.linkedin.com/in/marcus-vance-mock",
            "source_url": "https://cyber-corp.com/leadership",
            "person_confidence": 0.95
        },
        "mock-crypto.test": {
            "first_name": "Alice",
            "last_name": "Walker",
            "full_name": "Alice Walker",
            "role": "CTO & Co-Founder",
            "linkedin_url": "https://www.linkedin.com/in/alice-walker-mock",
            "source_url": "https://mock-crypto.test/team",
            "person_confidence": 0.95
        }
    }

    def find_leader(
        self,
        domain: str,
        company_name: Optional[str] = None,
        company_context: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        d_lower = (domain or "").lower().strip()
        if d_lower in self.MOCK_LEADERS:
            return dict(self.MOCK_LEADERS[d_lower])
        # Crucial: unknown domains in stub mode return None, never synthetic contacts
        return None
