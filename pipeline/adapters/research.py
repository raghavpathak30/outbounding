"""
Research Discovery Adapter utilizing ChatGoogleGenerativeAI with Google Search grounding
and strict HTTP domain verification.
"""
import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests

from pipeline.adapters.base import DiscoveryAdapter
from pipeline.config import (
    GEMINI_DISCOVERY_MODEL,
    get_discovery_model,
    execute_with_quota_retry,
    DailyQuotaExhaustedError,
    DAILY_QUOTA_RESET_MESSAGE,
)

logger = logging.getLogger("pipeline.adapters.research")


class ResearchDiscoveryAdapter(DiscoveryAdapter):
    """
    Discovery adapter using Gemini with web search grounding (Chat.send_message)
    to discover active tech startups matching targeted profile criteria:
      - Applied cryptography
      - Cybersecurity
      - Fintech fraud detection
      - AI/LLM infrastructure
      - AI security
    Supports company size filtering ('small', 'established', 'any').
    Enforces active domain resolution verification (HTTP HEAD/GET) on all candidate domains
    before returning them downstream.
    """

    TARGET_CRITERIA = [
        "applied cryptography (zero-knowledge proofs, MPC, homomorphic encryption, post-quantum cryptography)",
        "cybersecurity (confidential computing, enclave security, cloud/container security, vulnerability research)",
        "fintech fraud detection (real-time transaction anomaly detection, privacy-preserving screening, AML graph analysis)",
        "AI/LLM infrastructure (speculative decoding, inference optimization, distributed model serving, GPU orchestration, vLLM)",
        "AI security (LLM guardrails, jailbreak defenses, automated red-teaming, prompt injection defense, agent safety)"
    ]

    def __init__(self, model_name: Optional[str] = None):
        self.api_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
        self.model_name = model_name or get_discovery_model()
        self.discarded_log_file = os.getenv("DISCARDED_LOG_FILE", "discarded_candidates.jsonl")
        self.discarded_candidates: List[Dict[str, Any]] = []

    @staticmethod
    def _clean_domain(raw: str) -> str:
        """Strips protocol, www, trailing paths, query params, and fragments."""
        d = (raw or "").strip().lower()
        d = re.sub(r"^https?://", "", d)
        d = re.sub(r"^www\.", "", d)
        d = d.split("/")[0].split("?")[0].split("#")[0].strip()
        return d

    def verify_domain(self, domain: str) -> bool:
        """
        Performs real HTTP HEAD/GET check that the domain actually resolves and responds
        before passing it downstream.
        Returns True if domain resolves and responds (HTTP status < 500), False otherwise.
        """
        clean_d = self._clean_domain(domain)
        if not clean_d or "." not in clean_d or " " in clean_d:
            return False

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OutboundPipelineResearch/1.0",
            "Accept": "*/*"
        }

        self._last_verification_error = "domain_malformed_or_empty"
        for scheme in ["https", "http"]:
            url = f"{scheme}://{clean_d}"
            try:
                # First try HEAD request for fast header-only check
                resp = requests.head(
                    url,
                    timeout=5,
                    allow_redirects=True,
                    headers=headers
                )
                # Some servers return 405 Method Not Allowed or 403 Forbidden for HEAD
                if resp.status_code in [403, 405]:
                    resp = requests.get(
                        url,
                        timeout=5,
                        stream=True,
                        allow_redirects=True,
                        headers=headers
                    )
                if resp.status_code < 500:
                    self._last_verification_error = None
                    return True
                else:
                    self._last_verification_error = f"http_status_{resp.status_code}"
            except requests.exceptions.SSLError as e:
                self._last_verification_error = f"ssl_error: {e}"
                continue
            except requests.exceptions.Timeout as e:
                self._last_verification_error = f"timeout: {e}"
                continue
            except requests.exceptions.ConnectionError as e:
                self._last_verification_error = f"connection_or_dns_error: {e}"
                continue
            except requests.RequestException as e:
                self._last_verification_error = f"request_error: {e}"
                continue

        return False

    def _log_discarded_candidate(self, entry: Dict[str, Any]):
        """Logs discarded candidates separately for auditing grounding reliability."""
        logger.warning(
            f"[DISCARDED_CANDIDATE] Candidate '{entry.get('company_name')}' at domain '{entry.get('domain')}' "
            f"failed domain verification ({entry.get('reason')}). Discarded from pipeline."
        )
        if self.discarded_log_file:
            try:
                log_path = Path(self.discarded_log_file)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as e:
                logger.error(f"Failed to write to discarded log file {self.discarded_log_file}: {e}")

    def build_search_prompt(self, limit: int = 10, company_size: str = "any") -> str:
        """Builds structured prompt instructing Gemini to use Google Search tool."""
        size_filter = (company_size or "any").lower().strip()
        if size_filter == "small":
            size_instruction = (
                "Company size requirement: Filter strictly for early-stage startups and small engineering teams "
                "(approx. 1 to 10 employees, Seed or Pre-Seed stage)."
            )
        elif size_filter == "established":
            size_instruction = (
                "Company size requirement: Filter strictly for established, growth-stage tech companies and scaleups "
                "(approx. 20+ employees, Series A, Series B, or beyond)."
            )
        else:
            size_instruction = (
                "Company size requirement: Startups of any size (early-stage Seed to growth-stage Series B+)."
            )

        criteria_list = "\n".join(f"- {c}" for c in self.TARGET_CRITERIA)
        fetch_count = max(limit * 2, 10)

        prompt = (
            f"You are an expert technical intelligence agent. Use your Google Search tool to find real, currently operating "
            f"technology startups matching the following technical profile criteria:\n"
            f"{criteria_list}\n\n"
            f"{size_instruction}\n\n"
            f"MANDATORY SEARCH GROUNDING INSTRUCTIONS:\n"
            f"1. You MUST use Google Search to identify real, active startups with working public websites. Do NOT invent or hallucinate companies or domain names.\n"
            f"2. Every company MUST have an actual, working web domain.\n"
            f"3. Return exactly {fetch_count} unique candidates.\n\n"
            f"OUTPUT FORMAT REQUIREMENT:\n"
            f"Return ONLY a valid JSON array of objects. Do NOT include markdown code fences or conversational text.\n"
            f"Each JSON object must have the following keys:\n"
            f"- 'company_name': Full official company name\n"
            f"- 'domain': Clean website domain name ONLY (e.g. 'example.com' or 'example.ai' — no 'https://', no 'www.', no subpaths)\n"
            f"- 'size': Estimated employee count as an integer (e.g. 5, 35)\n"
            f"- 'industry': Specific domain focus (e.g. 'Applied Cryptography', 'AI Security')\n"
            f"- 'stage_signal': Specific funding or growth signal (e.g. 'Raised $4M Seed in 2025', 'Series A backed by Sequoia')\n"
            f"- 'company_context': A concise 1-2 sentence description explaining why this company matches our technical criteria and what specific product or architecture they build\n"
            f"- 'tech_stack': Comma-separated key technologies used (e.g. 'Rust, ZK-SNARKs, AWS Nitro Enclaves')\n"
        )
        return prompt

    def _query_gemini(self, prompt: str) -> str:
        """Invokes Gemini with Google Search tool via Chat.send_message with proactive RPM pacing and quota-aware 429 retry."""
        api_key = self.api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            logger.warning("GEMINI_API_KEY not set; research discovery cannot query live Gemini.")
            return ""

        def _call_gemini():
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            chat = client.chats.create(
                model=self.model_name,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.2,
                )
            )
            response = chat.send_message(prompt)
            if response:
                if hasattr(response, "text") and response.text:
                    return response.text
                elif response.candidates and response.candidates[0].content:
                    parts = response.candidates[0].content.parts or []
                    return "".join(getattr(p, "text", "") for p in parts if getattr(p, "text", ""))
                return str(response)
            return ""

        try:
            return execute_with_quota_retry(_call_gemini, adapter_name="ResearchDiscoveryAdapter")
        except DailyQuotaExhaustedError:
            raise
        except Exception as e:
            logger.error(f"Error invoking Gemini search grounding via Chat.send_message: {e}")
            return ""

    def _parse_llm_json(self, raw_text: str) -> List[Dict[str, Any]]:
        """Parses structured JSON candidate array from LLM response text."""
        if not raw_text or not raw_text.strip():
            return []

        text = raw_text.strip()
        # Handle markdown JSON blocks if present
        if "```json" in text:
            match = re.search(r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)
        elif "```" in text:
            match = re.search(r"```\s*(\[.*?\]|\{.*?\})\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for key in ["companies", "candidates", "results", "startups"]:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                return [data]
        except Exception:
            match = re.search(r"\[\s*\{.*\}\s*\]", raw_text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                    if isinstance(data, list):
                        return data
                except Exception as e:
                    logger.warning(f"Regex JSON fallback parsing failed: {e}")

        logger.warning(f"Could not parse structured JSON from LLM output: {raw_text[:200]}...")
        return []

    def discover(self, limit: int = 10, company_size: str = "any") -> List[Dict[str, Any]]:
        """
        Discovers uncontacted candidate companies matching profile criteria using
        grounded Gemini web search, verifying domain resolution via HTTP HEAD/GET before returning.
        """
        prompt = self.build_search_prompt(limit=limit, company_size=company_size)
        try:
            raw_output = self._query_gemini(prompt)
        except DailyQuotaExhaustedError:
            raise
        raw_items = self._parse_llm_json(raw_output)
        logger.info(f"Grounded search returned {len(raw_items)} candidate(s) prior to domain verification.")
        print(f"\n📡 Grounded Search returned {len(raw_items)} candidate(s) before domain verification:")
        for idx, item in enumerate(raw_items, 1):
            raw_dom = item.get("domain") or item.get("website") or item.get("url") or "unknown"
            name = item.get("company_name") or item.get("name") or raw_dom
            print(f"   {idx}. {name} ({raw_dom})")

        verified_candidates: List[Dict[str, Any]] = []

        for item in raw_items:
            if not isinstance(item, dict):
                continue

            raw_domain = item.get("domain") or item.get("website") or item.get("url") or ""
            domain = self._clean_domain(raw_domain)
            name = item.get("company_name") or item.get("name") or domain

            if not domain:
                continue

            # Anti-hallucination verification gate: HTTP HEAD/GET resolution check
            if not self.verify_domain(domain):
                failure_detail = getattr(self, "_last_verification_error", "domain_does_not_resolve_or_respond")
                discard_entry = {
                    "domain": domain,
                    "company_name": name,
                    "reason": "domain_does_not_resolve_or_respond",
                    "failure_detail": failure_detail,
                    "timestamp": datetime.now().isoformat(),
                    "raw_candidate": item
                }
                self.discarded_candidates.append(discard_entry)
                self._log_discarded_candidate(discard_entry)
                continue

            # Standardize candidate into identical adapter output shape
            raw_ctx = item.get("company_context")
            stage_signal = item.get("stage_signal") or item.get("signal") or ""
            tech_stack = item.get("tech_stack") or ""
            raw_size = item.get("size") or 0
            if isinstance(raw_size, str):
                digits = re.findall(r"\d+", raw_size)
                size_num = int(digits[0]) if digits else 0
            else:
                size_num = int(raw_size) if isinstance(raw_size, (int, float)) else 0

            industry = item.get("industry") or "Technology"

            if isinstance(raw_ctx, dict):
                headline = raw_ctx.get("headline") or f"{name} operating in {industry}"
                signal = raw_ctx.get("signal") or stage_signal or f"Scaling technical operations at {domain}"
                stack = raw_ctx.get("tech_stack") or tech_stack
            elif isinstance(raw_ctx, str) and raw_ctx.strip():
                headline = raw_ctx.strip()
                signal = stage_signal or headline
                stack = tech_stack
            else:
                headline = f"{name} operating in {industry}"
                signal = stage_signal or f"Scaling technical operations at {domain}"
                stack = tech_stack

            company_context = {
                "headline": headline,
                "signal": signal,
                "tech_stack": stack
            }

            candidate = {
                "domain": domain,
                "company_name": name,
                "industry": industry,
                "size": size_num,
                "stage_signal": stage_signal,
                "company_context": company_context
            }

            verified_candidates.append(candidate)
            if len(verified_candidates) >= limit:
                break

        return verified_candidates
