# Autonomous LangGraph Outbound Lead Pipeline

A production-grade, state-machine-driven outbound outreach pipeline built with [LangGraph](https://github.com/langchain-ai/langgraph). The system accepts company domains, discovers technical decision-makers via a multi-provider fallback cascade, dynamically crafts tailored pitches adapted to the contact's persona based on structured candidate resume data, and stages webhook payloads for campaign dispatch in Instantly.ai / Lemlist.

---

## 🛡️ Safety & Dry-Run Architecture

- **Default Zero-Network Execution**: All 3rd-party integrations (Apollo.io, PhantomBuster, Hunter.io, Gemini API, Instantly.ai/Lemlist) sit behind an Adapter pattern defaulting to `stub` mode. Default runs and tests execute 100% offline.
- **Hardcoded Payload Staging**: The `delivery_node` records all outbound payloads to `staged_deliveries/` with `DRY_RUN=True`.
- **Live Dispatch Protection**: Staging cannot be bypassed solely by switching to live adapters. Dispatching live emails requires:
  1. `DRY_RUN=false` in `.env`
  2. The explicit CLI flag `--confirm-live`

---

## 🏗️ StateGraph Topology

```
                  +-------------------+
                  |      START        |
                  +---------+---------+
                            |
                            v
                  +-------------------+
                  |  enrichment_node  |
                  +---------+---------+
                            |
                 [ has_valid_email? ]
                     /             \
           (No Email)               (Valid Email)
                 /                     \
                v                       v
      +-------------------+   +-------------------+
      |     skip_node     |   |   drafting_node   |
      +---------+---------+   +---------+---------+
                |                       |
                |                       v
                |             +-------------------+
                |             |   delivery_node   |
                |             +---------+---------+
                |                       |
                +-----------> <---------+
                            |
                            v
                  +-------------------+
                  |        END        |
                  +-------------------+
```

---

## 🔌 The Adapter Pattern

Each external integration is abstracted through an interface:
- **`EnrichmentAdapter`**:
  - `StubEnrichmentAdapter`: Returns deterministic leads based on domain keywords.
  - `LiveEnrichmentAdapter`: Apollo.io ➡️ PhantomBuster ➡️ Hunter.io (pattern-match + verification).
- **`DraftingAdapter`**:
  - `StubDraftingAdapter`: Deterministic persona-tailored pitches.
  - `LiveDraftingAdapter`: `ChatGoogleGenerativeAI` (`gemini-2.5-pro`) with local offline fallback.
- **`DeliveryAdapter`**:
  - `StubDeliveryAdapter`: Stages JSON payload to `staged_deliveries/`.
  - `LiveDeliveryAdapter`: Webhook dispatcher protected by the `--confirm-live` safety gate.

### Switching an Integration to Live
Modify `.env`:
```bash
# Toggle individual adapters
APOLLO_MODE=live
DRAFTING_MODE=live
DELIVERY_MODE=stub
```

---

## 🚀 Quickstart & Execution

### 1. Environment Setup
```bash
# Virtual environment & dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Run Tests (100% Offline)
```bash
pytest -v tests/
```

### 3. Run Pipeline CLI
```bash
# Single domain run (stub mode)
python main.py --domain cyber-corp.com

# AI/ML domain run
python main.py --domain ai-labs.io

# Domain with no discoverable email (triggers conditional bypass to END)
python main.py --domain invalid-domain.org

# Batch execution
python main.py --batch domains.txt
```

### 4. Manual Verification: Testing Live Apollo.io Enrichment
To test the live Apollo.io enrichment call against a real domain:
1. Configure your local `.env` with your real Apollo API key (never commit real credentials):
   ```bash
   APOLLO_MODE=live
   APOLLO_API_KEY=your_actual_apollo_key_here
   # Optional: set HUNTER_API_KEY if testing the Hunter fallback pattern verification path
   HUNTER_API_KEY=your_actual_hunter_key_here
   ENRICHMENT_DELAY_MS=500  # Delay between batch domain lookups in milliseconds
   ```
2. Run `main.py` against a target domain with `--auto-approve`:
   ```bash
   python main.py --domain target-company.com --auto-approve
   ```
3. Observe the enrichment and safety stages:
   - **Apollo Primary Call**: `LiveEnrichmentAdapter` calls `https://api.apollo.io/v1/people/match` to discover technical leaders and parse company signals (`funding`, `industry`, `keywords`, `tech_stack`) into `company_context`.
   - **Graceful Fallback Chain**: If Apollo returns `429` (rate limit), `401/403` (auth failure), or no usable match, it automatically degrades into PhantomBuster, and then Hunter.io.
   - **Hunter Verification Gate**: When pattern-guessed emails are produced in the Hunter fallback path, they pass through Hunter's `/v2/email-verifier`. Only `status == "valid"` emails proceed to `drafting_node`; ambiguous (`accept_all`, `unknown`) or invalid emails route directly to `skip_node`.
   - **Zero Live Dispatch**: Outbound payloads are safely staged into `staged_deliveries/` (`DRY_RUN=true`).

### 5. Live Delivery Webhook Integration (Instantly.ai / Lemlist)
The pipeline features a live webhook dispatch path in `LiveDeliveryAdapter`:
1. **Four Mandatory Safety Gates**: Real HTTP dispatch will ONLY execute when ALL of the following are true simultaneously:
   - `DELIVERY_MODE=live`
   - `DRY_RUN=false`
   - `--confirm-live` CLI flag was provided
   - `review_status == "approved"` (or approved after human inline editing)
   Missing any one condition automatically falls back to staging-only behavior with a clear log reason.
2. **First-Real-Send Friction Gate**: Even when `--confirm-live` is supplied, the adapter prints a summary of recipients and domains, and requires typing the exact recipient count (e.g. `Type 1 to confirm sending to this 1 person:`) before proceeding.
3. **Send-Rate Pacing**: Configure `DELIVERY_DELAY_MS` in `.env` to enforce a rate-limiting delay between consecutive live sends in a batch.
4. **Resilient Error Modes**: Real provider errors (429 rate limit, 401/403 auth, 400/422 payload rejection, timeouts) are captured, logged, and marked as `delivery_status="failed"` with `delivery_error`, ensuring batch executions never crash.

---

## 📂 Project Directory Layout
```
├── data/
│   └── resume.json                 # Modular resume highlights (placeholder contact info)
├── pipeline/
│   ├── state.py                    # PipelineState TypedDict definition
│   ├── adapters/
│   │   ├── base.py                 # Abstract Adapter interfaces & Factory
│   │   ├── stub.py                 # Deterministic zero-network mock adapters
│   │   └── live.py                 # Production live API adapters
│   ├── enrichment.py               # Enrichment node
│   ├── drafting.py                 # Drafting node & persona detection
│   ├── delivery.py                 # Delivery node & staging logic
│   └── graph.py                    # StateGraph construction & compilation
├── staged_deliveries/              # Destination for staged outbound JSON files
├── tests/
│   └── test_pipeline.py            # Complete offline unit test suite
├── main.py                         # CLI entrypoint
├── factory.py                      # Autonomous Software Factory (7 agents)
├── Dockerfile
└── docker-compose.yml
```
