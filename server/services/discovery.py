"""
Discovery service, deterministic 100-point ranking engine, and deduplication logic.
Orchestrates:
1. Campaign criteria extraction
2. DiscoveryAdapter invocation
3. Domain verification & normalization
4. Contact-history deduplication (JSONL + DB union)
5. 100-point deterministic ranking
6. Company candidate persistence
"""
import re
import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models.entities import Campaign, Company, Delivery
from pipeline.adapters.base import AdapterFactory, DiscoveryAdapter
from pipeline.contacted_log import is_already_contacted

logger = logging.getLogger("server.services.discovery")


# =====================================================================
# Domain Normalization & Cleaning
# =====================================================================

def normalize_domain(raw_domain: Optional[str]) -> str:
    """Strips protocol, www, trailing paths, query strings, and whitespace."""
    if not raw_domain:
        return ""
    d = raw_domain.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0].strip()
    return d


# =====================================================================
# Deterministic 100-Point Ranking Engine
# =====================================================================

class RankingEngine:
    """
    Computes a transparent, explainable 100-point match score:
    - Industry: 30 points
    - Technology: 30 points
    - Stage & Size: 20 points
    - Geography: 20 points
    Total = 100 points.
    """

    @classmethod
    def score_candidate(
        cls,
        campaign: Campaign,
        candidate_data: Dict[str, Any]
    ) -> Tuple[int, List[str], List[str]]:
        """
        Calculates match score, why_match explanations, and extracted technical signals.
        Returns: (match_score, why_match_list, technical_signals_list)
        """
        why_match: List[str] = []
        technical_signals: List[str] = []

        # Extract candidate properties
        cand_industry = (candidate_data.get("industry") or "").strip()
        cand_size = candidate_data.get("size")
        company_ctx = candidate_data.get("company_context") or {}
        headline = company_ctx.get("headline", "") if isinstance(company_ctx, dict) else ""
        signal = company_ctx.get("signal", "") if isinstance(company_ctx, dict) else ""
        tech_stack = company_ctx.get("tech_stack", "") if isinstance(company_ctx, dict) else ""
        cand_location = (candidate_data.get("location") or "").strip()

        if signal:
            technical_signals.append(f"Signal: {signal}")
        if tech_stack:
            technical_signals.append(f"Tech Stack: {tech_stack}")
        if headline:
            technical_signals.append(f"Headline: {headline}")

        # -------------------------------------------------------------
        # 1. Industry Scoring (Max 30 points)
        # -------------------------------------------------------------
        target_ind = (campaign.industry or "").lower().strip()
        cand_ind_lower = cand_industry.lower()
        combined_ind_text = f"{cand_ind_lower} {headline.lower()} {signal.lower()}"

        stop_words = {"and", "or", "the", "in", "of", "for", "to", "a", "&"}
        target_tokens = set(re.findall(r"\w+", target_ind)) - stop_words
        cand_tokens = set(re.findall(r"\w+", cand_ind_lower)) - stop_words
        text_tokens = set(re.findall(r"\w+", combined_ind_text)) - stop_words
        overlap = target_tokens.intersection(text_tokens)

        industry_score = 0
        if not target_ind:
            industry_score = 20
            why_match.append("Industry: General technology match (no specific filter) (+20)")
        elif cand_ind_lower and (target_ind in cand_ind_lower or cand_ind_lower in target_ind or (target_tokens and target_tokens.issubset(cand_tokens))):
            industry_score = 30
            why_match.append(f"Industry: Direct match with '{candidate_data.get('industry')}' (+30)")
        elif target_tokens and target_tokens.issubset(text_tokens):
            industry_score = 30
            why_match.append(f"Industry: Full keyword coverage ({', '.join(sorted(overlap))}) (+30)")
        elif len(overlap) >= 2:
            industry_score = 25
            why_match.append(f"Industry: High relevance overlap ({', '.join(sorted(overlap))}) (+25)")
        elif len(overlap) == 1:
            industry_score = 15
            why_match.append(f"Industry: Partial relevance overlap ({', '.join(sorted(overlap))}) (+15)")
        elif any(k in combined_ind_text for k in ["tech", "software", "infrastructure", "security", "ai"]):
            industry_score = 10
            why_match.append("Industry: Broad technology alignment (+10)")
        else:
            industry_score = 0
            why_match.append(f"Industry: No alignment with '{campaign.industry}' (+0)")

        # -------------------------------------------------------------
        # 2. Technology Scoring (Max 30 points)
        # -------------------------------------------------------------
        tech_list = []
        if campaign.technologies_json:
            try:
                tech_list = json.loads(campaign.technologies_json)
            except Exception:
                tech_list = []

        combined_tech_text = f"{tech_stack.lower()} {signal.lower()} {headline.lower()}".strip()

        tech_score = 0
        if not tech_list:
            tech_score = 20
            why_match.append("Technology: Standard engineering stack accepted (+20)")
        else:
            matched_techs = []
            for t in tech_list:
                t_clean = t.lower().strip()
                if not t_clean:
                    continue
                # Word-boundary or substring match
                pattern = r"(?<!\w)" + re.escape(t_clean) + r"(?!\w)"
                if re.search(pattern, combined_tech_text, re.IGNORECASE) or t_clean in combined_tech_text:
                    matched_techs.append(t)

            if matched_techs:
                ratio = len(matched_techs) / len(tech_list)
                tech_score = min(30, max(5, int(round(30 * ratio))))
                why_match.append(
                    f"Technology: Matched {len(matched_techs)}/{len(tech_list)} required technologies "
                    f"({', '.join(matched_techs)}) (+{tech_score})"
                )
            else:
                tech_score = 0
                why_match.append(f"Technology: None of the target technologies ({', '.join(tech_list[:4])}) identified (+0)")

        # -------------------------------------------------------------
        # 3. Stage & Size Scoring (Max 20 points: Size 10, Stage 10)
        # -------------------------------------------------------------
        # 3a. Size (Max 10)
        target_size = (campaign.company_size or "any").lower().strip()
        cand_size_int = None
        if cand_size is not None:
            try:
                cand_size_int = int(cand_size)
            except (ValueError, TypeError):
                cand_size_int = None

        size_score = 0
        if target_size == "any":
            size_score = 10
            why_match.append(f"Size: Flexible company size accepted (candidate has {cand_size_int or 'unspecified'} emp) (+10)")
        elif target_size == "small":
            if cand_size_int is not None and cand_size_int <= 10:
                size_score = 10
                why_match.append(f"Size: Perfectly aligns with small startup (size={cand_size_int} <= 10) (+10)")
            elif cand_size_int is not None and cand_size_int <= 20:
                size_score = 6
                why_match.append(f"Size: Close to small team threshold (size={cand_size_int}) (+6)")
            elif cand_size_int is not None and cand_size_int > 20:
                size_score = 0
                why_match.append(f"Size: Exceeds small size criteria (size={cand_size_int} > 20) (+0)")
            else:
                size_score = 5
                why_match.append("Size: Headcount data not published (+5)")
        elif target_size == "established":
            if cand_size_int is not None and cand_size_int > 20:
                size_score = 10
                why_match.append(f"Size: Established organization verified (size={cand_size_int} > 20) (+10)")
            elif cand_size_int is not None and cand_size_int >= 10:
                size_score = 6
                why_match.append(f"Size: Moderate team size (size={cand_size_int}) (+6)")
            elif cand_size_int is not None and cand_size_int < 10:
                size_score = 0
                why_match.append(f"Size: Below established size threshold (size={cand_size_int} < 10) (+0)")
            else:
                size_score = 5
                why_match.append("Size: Headcount data not published (+5)")
        else:
            size_score = 5

        # 3b. Stage (Max 10)
        target_stage = (campaign.company_stage or "").lower().strip()
        cand_stage_text = f"{candidate_data.get('stage_signal', '')} {signal} {headline}".lower()

        stage_score = 0
        if not target_stage or "any" in target_stage:
            stage_score = 10
            why_match.append("Stage: Any startup stage eligible (+10)")
        else:
            stage_keywords = set(re.findall(r"\w+", target_stage)) - {"and", "or", "stage", "startup"}
            matched_stage_words = [kw for kw in stage_keywords if kw in cand_stage_text]

            if matched_stage_words:
                stage_score = 10
                why_match.append(f"Stage: Direct alignment with '{campaign.company_stage}' (+10)")
            elif any(s in cand_stage_text for s in ["seed", "series a", "series b", "series c", "series d", "pre-seed", "grant", "bootstrapped", "venture"]):
                stage_score = 7
                why_match.append("Stage: Verified venture/grant backed stage (+7)")
            elif candidate_data.get("stage_signal") or signal:
                stage_score = 4
                why_match.append("Stage: High-velocity technical activity detected (+4)")
            else:
                stage_score = 0
                why_match.append(f"Stage: No evidence matching '{campaign.company_stage}' (+0)")

        # -------------------------------------------------------------
        # 4. Geography Scoring (Max 20 points)
        # -------------------------------------------------------------
        target_geo = (campaign.target_geography or "").lower().strip()
        domain = candidate_data.get("domain", "").lower()
        geo_text = f"{cand_location.lower()} {signal.lower()} {headline.lower()} {domain}"

        geo_score = 0
        if not target_geo or target_geo in ["any", "global", "remote", "worldwide"]:
            geo_score = 20
            why_match.append("Geography: Global/Remote search criteria (+20)")
        elif target_geo in cand_location.lower():
            geo_score = 20
            why_match.append(f"Geography: Exact location match ({candidate_data.get('location')}) (+20)")
        elif target_geo in geo_text:
            geo_score = 18
            why_match.append(f"Geography: Regional match with '{campaign.target_geography}' (+18)")
        elif target_geo == "india" and (domain.endswith(".in") or "india" in geo_text):
            geo_score = 20
            why_match.append("Geography: Verified Indian entity/TLD (+20)")
        elif target_geo in ["usa", "united states", "us"] and (domain.endswith(".us") or any(c in geo_text for c in ["san francisco", "new york", "austin", "seattle"])):
            geo_score = 20
            why_match.append("Geography: Verified US tech hub entity (+20)")
        elif not cand_location and not any(other_geo in geo_text for other_geo in ["usa", "europe", "germany", "singapore", "india"]):
            # Neutral / location unstated
            geo_score = 10
            why_match.append("Geography: Location unstated (neutral placement) (+10)")
        else:
            geo_score = 0
            why_match.append(f"Geography: Outside '{campaign.target_geography}' target region (+0)")

        total_score = min(100, max(0, industry_score + tech_score + size_score + stage_score + geo_score))
        return total_score, why_match, technical_signals


# =====================================================================
# Contact History Deduplication (JSONL + DB Union)
# =====================================================================

def is_domain_contacted(db: Session, domain: str) -> bool:
    """
    CRITICAL SAFETY GATE:
    Evaluates whether a domain has been contacted across all authoritative sources:
    1. Persistent JSONL log: pipeline/contacted_log.py
    2. Database Deliveries: status in ('staged', 'sent')
    3. Database Companies: selection_status == 'contacted'
    """
    clean_domain = normalize_domain(domain)
    if not clean_domain:
        return True

    # Source 1: Check CLI persistent JSONL log
    if is_already_contacted(domain=clean_domain):
        logger.info(f"Deduplication: {clean_domain} found in contacted_companies.jsonl")
        return True

    # Source 2: Check Database Deliveries
    has_delivery = db.execute(
        select(Delivery.id)
        .join(Company, Delivery.company_id == Company.id)
        .where(Company.domain == clean_domain, Delivery.delivery_status.in_(["staged", "sent"]))
        .limit(1)
    ).scalar_one_or_none()

    if has_delivery:
        logger.info(f"Deduplication: {clean_domain} found in database Deliveries")
        return True

    # Source 3: Check Database Company records with status 'contacted'
    has_contacted_comp = db.execute(
        select(Company.id)
        .where(Company.domain == clean_domain, Company.selection_status == "contacted")
        .limit(1)
    ).scalar_one_or_none()

    if has_contacted_comp:
        logger.info(f"Deduplication: {clean_domain} marked contacted in database Companies")
        return True

    return False


# =====================================================================
# Discovery Orchestration Service
# =====================================================================

class DiscoveryService:
    @classmethod
    def discover_for_campaign(
        cls,
        db: Session,
        user_id: str,
        campaign_id: str,
        limit: int = 10,
        adapter: Optional[DiscoveryAdapter] = None
    ) -> List[Company]:
        """
        Executes Phase 5 Discovery & Ranking:
        1. Validates campaign ownership.
        2. Queries DiscoveryAdapter with campaign criteria.
        3. Normalizes and validates domains.
        4. Deduplicates against existing campaign records and contacted history.
        5. Computes transparent 100-point deterministic match scores.
        6. Persists new Company records in status 'discovered'.
        7. Returns persisted candidates sorted by match score descending.
        """
        campaign = db.execute(
            select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user_id)
        ).scalar_one_or_none()

        if not campaign:
            raise ValueError(f"Campaign '{campaign_id}' not found or access unauthorized.")

        active_adapter = adapter or AdapterFactory.get_discovery_adapter()
        raw_candidates = active_adapter.discover(
            limit=limit * 2,  # Request larger pool to account for deduplication
            company_size=campaign.company_size
        )

        # Existing domains already attached to this campaign
        existing_campaign_domains = set(
            db.execute(
                select(Company.domain).where(Company.campaign_id == campaign_id)
            ).scalars().all()
        )

        persisted_companies: List[Company] = []
        seen_batch_domains = set()

        for cand in raw_candidates:
            if not isinstance(cand, dict):
                continue

            raw_d = cand.get("domain") or ""
            domain = normalize_domain(raw_d)

            # Verification check: discard empty or malformed domains
            if not domain or "." not in domain:
                continue

            # Batch deduplication
            if domain in seen_batch_domains:
                continue
            seen_batch_domains.add(domain)

            # Campaign deduplication
            if domain in existing_campaign_domains:
                logger.info(f"Skipping {domain}: already exists in campaign {campaign_id}")
                continue

            # Contacted history deduplication (JSONL + DB union)
            if is_domain_contacted(db, domain):
                logger.info(f"Skipping {domain}: previously contacted")
                continue

            # Compute transparent 100-point ranking score
            score, why_match, tech_signals = RankingEngine.score_candidate(campaign, cand)

            company_name = cand.get("company_name") or domain
            location = cand.get("location")
            industry = cand.get("industry")
            stage = cand.get("stage_signal") or cand.get("stage")
            size = cand.get("size")
            if size is not None:
                try:
                    size = int(size)
                except (ValueError, TypeError):
                    size = None

            source_name = getattr(active_adapter, "__class__", type(active_adapter)).__name__
            sources = [source_name]

            company = Company(
                campaign_id=campaign_id,
                domain=domain,
                company_name=company_name,
                location=location,
                industry=industry,
                stage=stage,
                size=size,
                match_score=score,
                why_match_json=json.dumps(why_match),
                technical_signals_json=json.dumps(tech_signals),
                sources_json=json.dumps(sources),
                selection_status="discovered",
            )
            db.add(company)
            persisted_companies.append(company)

            if len(persisted_companies) >= limit:
                break

        db.commit()
        for comp in persisted_companies:
            db.refresh(comp)

        # Sort by match_score descending
        persisted_companies.sort(key=lambda c: (c.match_score or 0), reverse=True)
        logger.info(
            f"Completed discovery for campaign={campaign_id}: "
            f"persisted={len(persisted_companies)} companies"
        )
        return persisted_companies
