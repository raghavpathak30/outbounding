"""
Base adapter interfaces and Factory pattern.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import os

class DiscoveryAdapter(ABC):
    @abstractmethod
    def discover(
        self,
        limit: int = 10,
        company_size: str = "any",
        targeting: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Discovers targeted companies matching candidate profile with optional size and modular campaign targeting."""
        pass

class EnrichmentAdapter(ABC):
    @abstractmethod
    def enrich(self, domain: str) -> Dict[str, Any]:
        """Enrich a target domain to discover contact info and company context."""
        pass

class PersonResearchAdapter(ABC):
    @abstractmethod
    def find_leader(
        self,
        domain: str,
        company_name: Optional[str] = None,
        company_context: Optional[Dict[str, Any]] = None,
        target_roles: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Discovers verified technical leader (Founder, CTO, VP Eng, Head of Eng, or campaign target_roles) for domain.
        Returns dict with keys: first_name, last_name, full_name, role, linkedin_url, source_url, person_confidence.
        Or None if no high-confidence leader verified.
        """
        pass

class EmailResolutionAdapter(ABC):
    @abstractmethod
    def resolve_email(
        self,
        domain: str,
        first_name: str,
        last_name: str,
        role: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Resolves and verifies deliverable business email for identified person.
        Returns dict with keys: email, score, status, provider, sources_count.
        Or None if no deliverable email could be verified.
        """
        pass

class DraftingAdapter(ABC):
    @abstractmethod
    def draft(self, role: Optional[str], domain: str, resume_context: Dict[str, Any], contact_name: Optional[str], company_context: Optional[Dict[str, Any]] = None) -> str:
        """Draft a tailored outreach pitch based on role, resume highlights, and optional company context."""
        pass

class DeliveryAdapter(ABC):
    @abstractmethod
    def deliver(self, payload: Dict[str, Any], dry_run: bool = True, confirm_live: bool = False, review_status: Optional[str] = None) -> Dict[str, Any]:
        """Stage or deliver outbound webhook payload."""
        pass

class AdapterFactory:
    """Factory to instantiate Stub or Live adapters based on environment configuration."""
    
    @staticmethod
    def get_discovery_adapter(targeting: Optional[Dict[str, Any]] = None) -> DiscoveryAdapter:
        mode = os.getenv("DISCOVERY_MODE", "stub").lower()
        if mode == "live":
            from pipeline.adapters.live import LiveDiscoveryAdapter
            return LiveDiscoveryAdapter(targeting=targeting)
        elif mode == "research":
            from pipeline.adapters.research import ResearchDiscoveryAdapter
            return ResearchDiscoveryAdapter(targeting=targeting)
        from pipeline.adapters.stub import StubDiscoveryAdapter
        return StubDiscoveryAdapter(targeting=targeting)

    @staticmethod
    def get_enrichment_adapter() -> EnrichmentAdapter:
        enrichment_mode = os.getenv("ENRICHMENT_MODE")
        if enrichment_mode:
            mode = enrichment_mode.lower()
        else:
            mode = os.getenv("APOLLO_MODE", "stub").lower()

        if mode in ["two_stage", "live"]:
            from pipeline.adapters.two_stage import TwoStageEnrichmentAdapter
            return TwoStageEnrichmentAdapter()
        elif mode == "legacy_live":
            from pipeline.adapters.live import LiveEnrichmentAdapter
            return LiveEnrichmentAdapter()
        from pipeline.adapters.stub import StubEnrichmentAdapter
        return StubEnrichmentAdapter()

    @staticmethod
    def get_person_research_adapter() -> PersonResearchAdapter:
        mode = os.getenv("PERSON_RESEARCH_MODE", os.getenv("ENRICHMENT_MODE", "stub")).lower()
        if mode in ["live", "two_stage", "research"]:
            from pipeline.adapters.person_research import GeminiPersonResearchAdapter
            return GeminiPersonResearchAdapter()
        from pipeline.adapters.person_research import StubPersonResearchAdapter
        return StubPersonResearchAdapter()

    @staticmethod
    def get_email_resolution_adapter() -> EmailResolutionAdapter:
        mode = os.getenv("EMAIL_RESOLUTION_MODE", os.getenv("ENRICHMENT_MODE", "stub")).lower()
        if mode in ["live", "two_stage", "hunter"]:
            from pipeline.adapters.email_resolution import HunterEmailResolver
            return HunterEmailResolver()
        from pipeline.adapters.email_resolution import StubEmailResolver
        return StubEmailResolver()

    @staticmethod
    def get_drafting_adapter() -> DraftingAdapter:
        mode = os.getenv("DRAFTING_MODE", "stub").lower()
        if mode == "live":
            from pipeline.adapters.live import LiveDraftingAdapter
            return LiveDraftingAdapter()
        from pipeline.adapters.stub import StubDraftingAdapter
        return StubDraftingAdapter()

    @staticmethod
    def get_delivery_adapter() -> DeliveryAdapter:
        mode = os.getenv("DELIVERY_MODE", "stub").lower()
        if mode == "live":
            from pipeline.adapters.live import LiveDeliveryAdapter
            return LiveDeliveryAdapter()
        from pipeline.adapters.stub import StubDeliveryAdapter
        return StubDeliveryAdapter()

    @staticmethod
    def get_resume_parsing_adapter():
        mode = os.getenv("RESUME_PARSING_MODE", "stub").lower()
        if mode in ["live", "gemini"]:
            from pipeline.adapters.resume_parsing import GeminiResumeParsingAdapter
            return GeminiResumeParsingAdapter()
        from pipeline.adapters.resume_parsing import StubResumeParsingAdapter
        return StubResumeParsingAdapter()

