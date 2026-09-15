# LangGraph Outbound Pipeline - Product Requirements Document (PRD)

## 1. Executive Summary & Project Goal
The target project is an intelligent, high-deliverability outbound outreach pipeline implemented as a LangGraph `StateGraph`. The pipeline takes a target company domain, enriches the lead with contact information (Name, Email, Role) using a tiered provider fallback chain, dynamically adapts outreach copy to the contact's persona based on candidate resume data, and stages webhook payloads for campaign dispatch in Instantly.ai / Lemlist.

## 2. Safety Invariants & Guardrails
- **Zero Live Network Calls in Default Mode**: All third-party integrations (Apollo.io, PhantomBuster, Hunter.io, Gemini API, Instantly.ai/Lemlist) sit behind modular adapter interfaces with both `Stub` and `Live` implementations.
- **Default Stub Mode**: By default, `APOLLO_MODE=stub`, `DRAFTING_MODE=stub`, and `DELIVERY_MODE=stub`. All default graph runs and unit tests execute strictly offline with zero external network dependencies.
- **Enforced DRY_RUN Staging**: `delivery_node` stages formatted outbound payloads into `staged_deliveries/` with `DRY_RUN=True` hardcoded as default.
- **Live Execution Gate**: Flipping adapters to `live` NEVER bypasses `DRY_RUN`. Staging remains active unless an explicit `--confirm-live` CLI flag is provided alongside `DRY_RUN=False`.
- **Privacy**: Personal contact details are protected; `data/resume.json` uses placeholder contact fields in git and is excluded via `.gitignore`.

## 3. State Schema Contract (`PipelineState`)
The LangGraph pipeline operates over a typed state dictionary (`PipelineState`):
- `domain` (str): Target domain to enrich (e.g. "acme-corp.com").
- `contact_name` (Optional[str]): Discovered or enriched contact name.
- `contact_email` (Optional[str]): Discovered contact email address.
- `contact_role` (Optional[str]): Contact professional title (e.g. "Head of Information Security", "VP of AI", "Director of Talent").
- `resume_context` (dict): Structured resume highlights partitioned by technical domain.
- `email_draft` (Optional[str]): Personalized outreach copy.
- `delivery_status` (Optional[str]): Execution status: `"staged"`, `"skipped_no_email"`, or `"sent"`.

## 4. Adapter Interface Specifications & Contracts

### 4.1 EnrichmentAdapter
- `enrich(domain: str) -> dict`:
  - Returns `{"contact_name": str, "contact_email": Optional[str], "contact_role": Optional[str]}`.
  - **Stub Contract**: Returns deterministic realistic lead data based on domain rules. If domain indicates invalid (e.g. "invalid-domain.com" or "no-email.org"), returns `contact_email=None`.
  - **Live Contract**:
    1. Primary: Apollo.io People Match API (`/v1/people/match` or `/v1/mixed_people/search`).
    2. Fallback 1: PhantomBuster API.
    3. Fallback 2: Hunter.io domain search pattern matching (`{first}.{last}@{domain}`).
    - **Verification Requirement**: Hunter fallback MUST verify pattern-guessed emails via verification endpoint before returning as valid. If unverified, email is rejected.

### 4.2 DraftingAdapter
- `draft(role: Optional[str], domain: str, resume_context: dict, contact_name: Optional[str]) -> str`:
  - **Stub Contract**: Returns deterministic, persona-adapted copy referencing specific project bullets.
  - **Live Contract**: Connects to `ChatGoogleGenerativeAI` using current Gemini model (e.g., `gemini-2.5-pro` or `gemini-1.5-pro` with dynamic model fallback). If API key is not configured, gracefully falls back to structured offline synthesis.

### 4.3 DeliveryAdapter
- `deliver(payload: dict, dry_run: bool = True, confirm_live: bool = False) -> dict`:
  - Formats Instantly.ai / Lemlist webhook payload with:
    - Sender identity: `Raghav Pathak <raghav.candidate.outreach@example.com>`
    - Target recipient & custom variables
    - Email body
    - Mandatory unsubscribe / opt-out placeholder footer
  - **Safety Gate**: If `dry_run=True` or `confirm_live=False`, writes payload to `staged_deliveries/{domain}_{timestamp}.json` and returns `{"status": "staged", "path": ...}`. Never performs outbound HTTP POST without explicit authorization.

## 5. Persona Adaptation Matrix
The drafting engine classifies `contact_role` into one of three personas:
1. **Security / Infrastructure Leads**:
   - Focus: Hands-on cybersecurity, timing side-channel attacks, DSS modular arithmetic, CKKS homomorphic encryption (0.979 AUC, 5x speedup, 249x compression), SetuGuard Android threat detection, Hack The Box Skilled rank, Intigriti bug bounty.
2. **AI / Machine Learning Leads**:
   - Focus: End-to-end application architecture, low-latency Gemini API integrations via Google AI Studio, SetuGuard RAG pipeline (FAISS + Mistral 7B + hallucination grounding gate), Dispute Desk solo hackathon builder (Razorpay AI Buildathon), PwnBot tool-calling agent.
3. **HR / Talent Acquisition**:
   - Focus: ATS-optimized high-impact summary, B.Tech CSE (LNMIIT 2023-2027), National Hackathon Grand Finalist at IIT Hyderabad, Head of Sponsorship at Vivacity, high velocity, fast team integration.

## 6. Graph Topology & Conditional Routing
- `START -> enrichment_node`
- `enrichment_node -> conditional_router`:
  - If `contact_email` is valid: route to `drafting_node`
  - If `contact_email` is None or invalid: route to `skip_node -> END` (bypassing drafting and delivery, setting `delivery_status="skipped_no_email"`)
- `drafting_node -> delivery_node -> END`
