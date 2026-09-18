"""
Resume parsing adapters for extracting structured candidate achievements.
Categorizes experience into three outreach personas:
1. security_infrastructure
2. ai_machine_learning
3. hr_talent_acquisition
Plus personal contact information.
"""
import os
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional

from pypdf import PdfReader

from pipeline.adapters._llm_text import extract_llm_text
from pipeline.config import (
    DEFAULT_GEMINI_MODEL,
    execute_with_quota_retry,
    pace_gemini_call,
)

logger = logging.getLogger("pipeline.adapters.resume_parsing")


class ResumeParsingAdapter(ABC):
    """Abstract contract for parsing candidate resumes into structured persona categories."""

    @abstractmethod
    def parse(self, file_path: str, is_json: bool = False) -> Dict[str, Any]:
        """
        Parses a resume file (PDF or JSON) and returns a structured dictionary
        matching the persona categorizations.

        Returns:
            Dict with keys:
            - 'personal': name, title, email, phone, location, github, linkedin, portfolio
            - 'security_infrastructure': summary, highlights (list), core_stack (list)
            - 'ai_machine_learning': summary, highlights (list), core_stack (list)
            - 'hr_talent_acquisition': summary, highlights (list), core_stack (list)
        """
        pass


class StubResumeParsingAdapter(ResumeParsingAdapter):
    """
    Deterministic, zero-network fixture adapter for testing and offline development.
    Guarantees consistent, schema-compliant output without external API calls.
    """

    DEFAULT_FIXTURE: Dict[str, Any] = {
        "personal": {
            "name": "Raghav Pathak",
            "title": "Security & AI Engineer",
            "email": "raghav.candidate.outreach@example.com",
            "phone": "+1 (555) 019-2834",
            "location": "Jaipur / Noida, India",
            "github": "https://github.com/raghavpathak30",
            "linkedin": "https://linkedin.com/in/raghav-pathak",
            "portfolio": "https://raghavpathak.dev"
        },
        "security_infrastructure": {
            "summary": "Specialist in applied cryptography, timing side-channel attack analysis, and containerized DevSecOps pipelines.",
            "highlights": [
                "Engineered timing side-channel attacks and conducted vulnerability research on DSS modular arithmetic implementations.",
                "Architected CKKS homomorphic encryption fraud-scoring service in C++ and Microsoft SEAL achieving 0.979 AUC on live bank transaction streams.",
                "Accelerated cryptographic computation 4.98x over Lattigo and reduced per-transaction payload 249x using Go stream ciphering.",
                "Co-developed SetuGuard banking threat detection platform; Grand Finalist at IIT Hyderabad PSB CyberShield 2026.",
                "Skilled Rank on Hack The Box Academy; active bug bounty researcher targeting access control flaws on Intigriti."
            ],
            "core_stack": [
                "C++17", "Python", "Go", "Microsoft SEAL", "Docker", "Burp Suite", "Trivy", "Terraform", "OWASP Top 10"
            ]
        },
        "ai_machine_learning": {
            "summary": "AI Systems Engineer specializing in low-latency LLM agent architectures, schema-constrained generation, and RAG grounding gates.",
            "highlights": [
                "Designed end-to-end multi-agent architectures and low-latency Gemini API integrations via Google AI Studio.",
                "Built Dispute Desk solo in 5 days for Razorpay AI Buildathon 2026, placing an LLM directly in the decision path for chargeback-evidence generation.",
                "Engineered SetuGuard RAG pipeline over Android corpus using FAISS and local Mistral 7B, eliminating hallucinations via schema-constrained chunk gating.",
                "Developed PwnBot, an autonomous tool-calling agent with strict execution scope guards and parsed typed CLI outputs.",
                "Accelerated dataset scoring 11x (7.6s to 0.66s) and reduced peak memory 2.9x through precomputed artifact caching."
            ],
            "core_stack": [
                "LangGraph", "LangChain", "Gemini API", "Python", "FAISS", "Mistral 7B", "FastAPI", "Pydantic", "Docker"
            ]
        },
        "hr_talent_acquisition": {
            "summary": "High-velocity builder and B.Tech CSE candidate at LNMIIT with proven cross-functional leadership and national-level hackathon achievements.",
            "highlights": [
                "B.Tech in Computer Science and Engineering from LNMIIT (2023-2027), excelling in systems engineering and applied AI.",
                "National Grand Finalist (Top 4 teams) at PSB CyberShield 2026 banking cybersecurity hackathon at IIT Hyderabad.",
                "Head of Sponsorship for Vivacity, leading corporate outreach and closing major corporate partnerships.",
                "Google Cybersecurity Professional Certificate (2025) covering DevSecOps, containerization, and automated CI/CD security.",
                "Proven track record of independently delivering production-grade solo and team software projects within tight deadlines."
            ],
            "core_stack": [
                "Full-Stack Problem Solving", "Systems Design", "Technical Communication", "Cross-Functional Leadership"
            ]
        }
    }

    def parse(self, file_path: str, is_json: bool = False) -> Dict[str, Any]:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Resume file not found at path: {file_path}")

        # If it is a JSON file, attempt to parse its actual contents
        if is_json or p.suffix.lower() == ".json":
            try:
                content = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(content, dict) and "personal" in content:
                    return content
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSON in resume file: {exc}") from exc

        # Return a deep copy of deterministic fixture
        return json.loads(json.dumps(self.DEFAULT_FIXTURE))


class GeminiResumeParsingAdapter(ResumeParsingAdapter):
    """
    Production parser leveraging Gemini Flash to extract structured achievements
    into the 3 persona categories from raw PDF text or JSON.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.api_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
        self.model_name = model_name or os.getenv("GEMINI_RESUME_PARSING_MODEL", DEFAULT_GEMINI_MODEL)

    def extract_text_from_pdf(self, file_path: str) -> str:
        """Extracts plain text from PDF pages using pypdf."""
        try:
            reader = PdfReader(file_path)
            extracted = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text:
                    extracted.append(text)
            full_text = "\n".join(extracted).strip()
            if not full_text:
                raise ValueError("Extracted text from PDF is empty.")
            return full_text
        except Exception as e:
            logger.error(f"Failed to extract text from PDF: {type(e).__name__}")
            raise ValueError(f"Could not read PDF file: {e}") from e

    def build_parsing_prompt(self, resume_text: str) -> str:
        """Constructs schema-constrained prompt for structured extraction."""
        return (
            "You are an expert technical recruiter and resume analyzer. "
            "Analyze the candidate resume text provided below and extract structured achievements "
            "into EXACTLY four distinct categories in valid JSON format:\n\n"
            "1. 'personal': Contact and web links with keys:\n"
            "   - 'name': Candidate full name\n"
            "   - 'title': Professional headline/title\n"
            "   - 'email': Candidate contact email\n"
            "   - 'phone': Contact phone number or null\n"
            "   - 'location': Geographic location or null\n"
            "   - 'github': GitHub profile URL or null\n"
            "   - 'linkedin': LinkedIn profile URL or null\n"
            "   - 'portfolio': Personal portfolio website URL or null\n\n"
            "2. 'security_infrastructure': Technical experience in systems security, applied cryptography, "
            "DevSecOps, enclaves, penetration testing, side-channels, or network protocols. Keys:\n"
            "   - 'summary': High-level executive summary (1-2 sentences)\n"
            "   - 'highlights': List of 3-5 specific, bulleted technical achievements with metrics\n"
            "   - 'core_stack': List of relevant programming languages, tools, and protocols\n\n"
            "3. 'ai_machine_learning': Technical experience in AI systems, LLM orchestration, agentic pipelines, "
            "RAG, machine learning models, inference optimization, or data pipelines. Keys:\n"
            "   - 'summary': High-level executive summary (1-2 sentences)\n"
            "   - 'highlights': List of 3-5 specific, bulleted technical achievements with metrics\n"
            "   - 'core_stack': List of relevant frameworks, models, libraries, and tools\n\n"
            "4. 'hr_talent_acquisition': High-level background for recruiters and HR leaders. Keys:\n"
            "   - 'summary': Broad impact summary emphasizing velocity, problem-solving, and adaptability\n"
            "   - 'highlights': List of 3-5 key qualifications (degree, university, honors, hackathons, leadership)\n"
            "   - 'core_stack': List of core competencies and cross-functional skills\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "- Return ONLY valid JSON, with NO surrounding explanation or conversational text.\n"
            "- Do not invent or fabricate false metrics or achievements; strictly extract and categorize grounded facts.\n\n"
            f"--- CANDIDATE RESUME TEXT ---\n{resume_text}\n--- END RESUME TEXT ---"
        )

    def parse(self, file_path: str, is_json: bool = False) -> Dict[str, Any]:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Resume file not found at path: {file_path}")

        # If JSON input, parse directly
        if is_json or p.suffix.lower() == ".json":
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "personal" in data and "security_infrastructure" in data:
                    return data
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSON in resume file: {exc}") from exc

        # Extract text from PDF
        resume_text = self.extract_text_from_pdf(file_path)

        if not self.api_key:
            logger.warning("No GEMINI_API_KEY configured; falling back to Stub parser output.")
            stub = StubResumeParsingAdapter()
            return stub.parse(file_path, is_json=False)

        prompt = self.build_parsing_prompt(resume_text)

        pace_gemini_call()

        def _call_gemini():
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                google_api_key=self.api_key,
                temperature=0.1,
            )
            return llm.invoke([{"role": "user", "content": prompt}])

        response = execute_with_quota_retry(_call_gemini)
        raw_output = extract_llm_text(response) or ""

        # Strip optional markdown code block
        cleaned = raw_output.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Gemini output could not be decoded as JSON: {e}")
            raise ValueError(f"Gemini output could not be decoded as JSON: {e}") from e

        # Basic schema integrity check
        required_keys = ["personal", "security_infrastructure", "ai_machine_learning", "hr_talent_acquisition"]
        for key in required_keys:
            if key not in parsed:
                raise ValueError(f"Gemini output missing required section: '{key}'")

        return parsed
