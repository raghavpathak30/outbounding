"""
Stub adapter implementations for zero-network execution and offline testing.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
import json
from pathlib import Path
from pipeline.adapters.base import DiscoveryAdapter, EnrichmentAdapter, DraftingAdapter, DeliveryAdapter

class StubDiscoveryAdapter(DiscoveryAdapter):
    """
    Returns deterministic, rotating candidate companies matching candidate technical profile.
    Supports size filtering: 'small' (<=10 emp), 'established' (>20 emp), or 'any'.
    """
    _rotation_idx: int = 0

    CANDIDATES = [
        # Cryptography & Security (small)
        {
            "domain": "vault-mesh-crypto.io",
            "company_name": "VaultMesh Cryptography",
            "company_context": {
                "headline": "Early-stage cryptographic infrastructure building zero-knowledge state channels and MPC protocols",
                "signal": "Closed $4.5M Seed round to deploy threshold signature enclaves for cross-chain settlements",
                "tech_stack": "Rust, MPC, ZK-SNARKs, AWS Nitro Enclaves"
            },
            "size": 5,
            "industry": "Applied Cryptography & Web3 Security"
        },
        # AI Infrastructure (small)
        {
            "domain": "sentinel-prompt-labs.io",
            "company_name": "Sentinel Prompt Labs",
            "company_context": {
                "headline": "Boutique AI security firm engineering real-time guardrails and red-teaming for autonomous LLM agents",
                "signal": "Announced $2.2M pre-seed to build automated jailbreak defenses for financial and healthcare agents",
                "tech_stack": "Python, Gemini API, PyTorch, vLLM, FastEmbed"
            },
            "size": 4,
            "industry": "AI Security & Safety"
        },
        # AI Infrastructure (established)
        {
            "domain": "prism-inference-core.ai",
            "company_name": "Prism Inference Core",
            "company_context": {
                "headline": "High-throughput inference platform specializing in distributed speculative decoding and custom CUDA kernels",
                "signal": "Raised $22M Series A to scale ultra-low latency model serving across multi-node GPU clusters",
                "tech_stack": "C++, CUDA, TensorRT-LLM, Triton, Python"
            },
            "size": 35,
            "industry": "AI/LLM Infrastructure"
        },
        # Cybersecurity & Infrastructure (established)
        {
            "domain": "enclave-defense-systems.com",
            "company_name": "Enclave Defense Systems",
            "company_context": {
                "headline": "Hardware-enforced confidential computing systems protecting containerized cloud workloads",
                "signal": "Secured $30M Series B expansion for zero-trust secure enclave orchestration in banking",
                "tech_stack": "Rust, Linux Kernel, AMD SEV-SNP, Intel SGX, Docker"
            },
            "size": 55,
            "industry": "Cybersecurity & Confidential Computing"
        },
        # Fintech Fraud Detection (small)
        {
            "domain": "cipher-settle-vault.co",
            "company_name": "CipherSettle Vault",
            "company_context": {
                "headline": "Homomorphic encryption microservice for interbank privacy-preserving fraud anomaly scoring",
                "signal": "Backed by top fintech angels with $3.5M seed to eliminate plaintext PII during transaction screening",
                "tech_stack": "Microsoft SEAL, C++, Python, Kafka, Redis"
            },
            "size": 8,
            "industry": "Fintech Fraud Detection & Privacy"
        },
        # Fintech Fraud Detection (established)
        {
            "domain": "stream-guard-fintech.io",
            "company_name": "StreamGuard Technologies",
            "company_context": {
                "headline": "Real-time payment fraud prevention network powered by sub-10ms graph neural network inference",
                "signal": "Processing over $5B annual volume with 99.8% precision across tier-1 card network transactions",
                "tech_stack": "Go, Python, PyTorch Geometric, ScyllaDB, gRPC"
            },
            "size": 42,
            "industry": "Fintech Cybersecurity & Fraud"
        },
        # AI Security (established)
        {
            "domain": "neuron-shield-security.com",
            "company_name": "NeuronShield Security",
            "company_context": {
                "headline": "Enterprise data loss prevention and indirect prompt injection defense platform for workplace copilots",
                "signal": "Series A funded ($16M) with 40+ enterprise deployments in defense and healthcare sectors",
                "tech_stack": "Rust, Python, LangChain, Kubernetes, AWS"
            },
            "size": 28,
            "industry": "Enterprise AI Security"
        },
        # Cryptography (small)
        {
            "domain": "aegis-quantum-cipher.io",
            "company_name": "Aegis Quantum Cipher",
            "company_context": {
                "headline": "Post-quantum cryptographic migration toolkit replacing classical public key schemes with lattice-based ciphers",
                "signal": "Awarded NSF SBIR grant and $2M angel funding for NIST PQC standard Kyber and Dilithium acceleration",
                "tech_stack": "C, Assembly, Rust, OpenSSL, Linux"
            },
            "size": 6,
            "industry": "Applied Cryptography"
        }
    ]

    @classmethod
    def reset_rotation(cls):
        """Resets the rotation pointer for deterministic testing."""
        cls._rotation_idx = 0

    def discover(self, limit: int = 10, company_size: str = "any") -> List[Dict[str, Any]]:
        size_filter = (company_size or "any").lower().strip()
        if size_filter == "small":
            candidates = [c for c in self.CANDIDATES if c["size"] <= 10]
        elif size_filter == "established":
            candidates = [c for c in self.CANDIDATES if c["size"] > 20]
        else:
            candidates = list(self.CANDIDATES)

        if not candidates:
            candidates = list(self.CANDIDATES)

        count = min(limit, len(candidates))
        selected = []
        for i in range(count):
            idx = (StubDiscoveryAdapter._rotation_idx + i) % len(candidates)
            selected.append(dict(candidates[idx]))

        StubDiscoveryAdapter._rotation_idx = (StubDiscoveryAdapter._rotation_idx + count) % len(candidates)
        return selected



class StubEnrichmentAdapter(EnrichmentAdapter):
    """Returns deterministic fake contact profiles based on target domain keywords."""

    EXPLICIT_DOMAINS = {
        "apex-vault-fintech.io": {
            "contact_name": "Devon Sterling",
            "contact_email": "devon.sterling@apex-vault-fintech.io",
            "contact_role": "Chief Information Security Officer & VP Infrastructure",
            "company_context": {
                "headline": "Series B fintech scaling zero-knowledge asset custody and real-time transaction security",
                "signal": "Announced $28M Series B expansion to build out privacy-preserving encrypted settlement architecture",
                "tech_stack": "Rust, AWS Nitro Enclaves, HSMs, Kubernetes"
            }
        },
        "hyperion-inference-labs.io": {
            "contact_name": "Dr. Maya Lin",
            "contact_email": "maya.lin@hyperion-inference-labs.io",
            "contact_role": "VP of AI Systems & Low-Latency LLM Infrastructure",
            "company_context": {
                "headline": "Applied AI infrastructure lab optimizing sub-50ms LLM serving and autonomous agent execution loops",
                "signal": "Open-sourced high-throughput speculative decoding engine and scaling low-latency agent loops",
                "tech_stack": "vLLM, TensorRT-LLM, Python, C++, Gemini orchestration"
            }
        },
        "nexus-talent-partners.co": {
            "contact_name": "Julian Rivera",
            "contact_email": "julian.rivera@nexus-talent-partners.co",
            "contact_role": "Director of Technical Talent & Engineering Recruiting",
            "company_context": {
                "headline": "Specialized technical recruiting partner placing founding engineers across AI & systems infrastructure",
                "signal": "Partnered with high-growth seed/Series-A startups building autonomous developer tooling and security platforms",
                "tech_stack": "Systems programming, distributed infrastructure, LLM engineering"
            }
        },
        "cyber-corp.com": {
            "contact_name": "Marcus Vance",
            "contact_email": "marcus.vance@cyber-corp.com",
            "contact_role": "Head of Information Security & Infrastructure",
            "company_context": {
                "headline": "Enterprise security infrastructure and confidential computing systems",
                "signal": "Protecting cloud workloads with timing side-channel defenses and applied cryptography",
                "tech_stack": "Rust, Linux Kernel, C++, AWS Nitro Enclaves"
            }
        }
    }

    def _verify_email(self, email: str) -> str:
        """
        Deterministic stub email verifier for testing data quality gates.
        Returns: 'valid', 'invalid', 'accept_all', or 'unknown'.
        """
        if not email or "@" not in email:
            return "invalid"
        e_lower = email.lower()
        if "invalid" in e_lower or "unverified" in e_lower:
            return "invalid"
        if "accept-all" in e_lower or "accept_all" in e_lower:
            return "accept_all"
        if "unknown" in e_lower or "ambiguous" in e_lower:
            return "unknown"
        return "valid"

    def enrich(self, domain: str) -> Dict[str, Any]:
        domain_lower = domain.lower()
        
        # Test case for conditional bypass: missing / invalid emails
        if "invalid" in domain_lower or "no-email" in domain_lower or "missing" in domain_lower:
            return {
                "contact_name": None,
                "contact_email": None,
                "contact_role": None,
                "company_context": None
            }

        # Check explicit persona test domains
        if domain_lower in self.EXPLICIT_DOMAINS:
            lead = dict(self.EXPLICIT_DOMAINS[domain_lower])
            if lead.get("contact_email") and self._verify_email(lead["contact_email"]) != "valid":
                lead["contact_email"] = None
            return lead
        
        # Test case for unverified / ambiguous / accept_all pattern verification
        if any(k in domain_lower for k in ["unverified", "ambiguous", "accept-all", "accept_all", "unknown"]):
            candidate_email = f"lead@{domain}"
            verification_status = self._verify_email(candidate_email)
            if verification_status != "valid":
                return {
                    "contact_name": "Unverified Lead",
                    "contact_email": None,  # Rejected by verification gate
                    "contact_role": "Lead Architect",
                    "company_context": None
                }

        # Security / Fintech domain keyword rule for offline test suites
        sec_tokens = ["security", "cyber", "shield", "fintech", "vault", "crypt", "-sec", "sec-"]
        if any(k in domain_lower for k in sec_tokens):
            email = f"marcus.vance@{domain}"
            return {
                "contact_name": "Marcus Vance",
                "contact_email": email if self._verify_email(email) == "valid" else None,
                "contact_role": "Head of Information Security & Infrastructure",
                "company_context": None
            }

        # AI / ML domain rule for offline test suites (avoid matching 'ai' substring inside 'domain')
        ai_tokens = ["-ai", "ai-", ".ai", "-ml", "ml-", "labs", "tech", "inference", "neural", "guardrail"]
        if any(k in domain_lower for k in ai_tokens):
            email = f"elena.rostova@{domain}"
            return {
                "contact_name": "Dr. Elena Rostova",
                "contact_email": email if self._verify_email(email) == "valid" else None,
                "contact_role": "VP of AI Engineering & Applied ML",
                "company_context": None
            }

        # HR / Talent domain rule for offline test suites
        talent_tokens = ["talent", "people", "recruit", "hr-", "-hr"]
        if any(k in domain_lower for k in talent_tokens):
            email = f"sarah.jenkins@{domain}"
            return {
                "contact_name": "Sarah Jenkins",
                "contact_email": email if self._verify_email(email) == "valid" else None,
                "contact_role": "Director of Technical Talent Acquisition",
                "company_context": None
            }

        # Default for unknown domains: clean None without fabricating synthetic leads (NEVER Alex Morgan)
        return {
            "contact_name": None,
            "contact_email": None,
            "contact_role": None,
            "company_context": None
        }

class StubDraftingAdapter(DraftingAdapter):
    """Returns structured, deterministic outreach pitches mapped to personas."""

    def draft(self, role: Optional[str], domain: str, resume_context: Dict[str, Any], contact_name: Optional[str], company_context: Optional[Dict[str, Any]] = None) -> str:
        role_str = (role or "").lower()
        name_greeting = f"Hi {contact_name}," if contact_name else "Hello,"

        is_ai = any(w in role_str for w in ["ai", "ml", "machine learning", "data science", "llm", "deep learning", "inference", "neural"])
        is_sec = any(w in role_str for w in ["security", "ciso", "secops", "crypt", "cyber", "pentest", "vulnerability"]) or ("infra" in role_str and not is_ai)

        if is_ai:
            ai = resume_context.get("ai_machine_learning", {})
            h = ai.get("highlights", [
                "End-to-end multi-agent architectures and low-latency Gemini API integrations via Google AI Studio",
                "Dispute Desk solo hackathon builder at Razorpay AI Buildathon 2026"
            ])
            return (
                f"{name_greeting}\n\n"
                f"I have been following your engineering initiatives in applied AI and agentic systems at {domain}. "
                f"As an AI Systems Engineer, I specialize in production LLM pipelines and low-latency API orchestration.\n\n"
                f"Selected highlights:\n"
                f"• {h[0]}\n"
                f"• {h[1]}\n\n"
                f"I would love to connect and share insights on low-latency agent orchestration.\n\n"
                f"Best regards,\nRaghav Pathak"
            )

        elif is_sec:
            sec = resume_context.get("security_infrastructure", {})
            h = sec.get("highlights", [
                "Timing side-channel attack analysis on DSS modular arithmetic",
                "CKKS homomorphic encryption fraud detection service (0.979 AUC, 5x speedup)"
            ])
            return (
                f"{name_greeting}\n\n"
                f"I noticed your focus on security and infrastructure resilience at {domain}. "
                f"I am an applied security and cryptography researcher with hands-on experience in vulnerability research.\n\n"
                f"Key relevant achievements:\n"
                f"• {h[0]}\n"
                f"• {h[1]}\n\n"
                f"I would welcome the opportunity to discuss how these systems-level security practices could support your team at {domain}.\n\n"
                f"Best regards,\nRaghav Pathak"
            )

        else:
            # HR / General persona
            hr = resume_context.get("hr_talent_acquisition", {})
            h = hr.get("highlights", [
                "B.Tech Computer Science & Engineering candidate at LNMIIT (2023-2027)",
                "National Grand Finalist at PSB CyberShield 2026 (IIT Hyderabad)"
            ])
            return (
                f"{name_greeting}\n\n"
                f"I am writing to express my strong interest in engineering opportunities with your team at {domain}. "
                f"I am a high-velocity software engineer combining strong fundamentals in systems security with applied AI.\n\n"
                f"Key qualifications:\n"
                f"• {h[0]}\n"
                f"• {h[1]}\n\n"
                f"I would appreciate the chance to discuss potential alignment with open roles at {domain}.\n\n"
                f"Sincerely,\nRaghav Pathak"
            )

class StubDeliveryAdapter(DeliveryAdapter):
    """Stages payload locally without performing any external network dispatch."""

    def deliver(self, payload: Dict[str, Any], dry_run: bool = True, confirm_live: bool = False, review_status: Optional[str] = None) -> Dict[str, Any]:
        staged_dir = Path("staged_deliveries")
        staged_dir.mkdir(parents=True, exist_ok=True)
        domain = payload.get("domain", "unknown").replace(".", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = staged_dir / f"staged_{domain}_{timestamp}.json"
        
        record = {
            "mode": "stub",
            "dry_run": True,
            "staged_at": datetime.now().isoformat(),
            "payload": payload,
            "mock_response": {
                "status": 200,
                "message": "Simulated delivery staged successfully",
                "campaign_id": "camp_mock_instantly_9941"
            }
        }
        filename.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return {
            "status": "staged",
            "file": str(filename),
            "simulated_response": record["mock_response"]
        }
