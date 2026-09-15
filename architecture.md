# LangGraph Outbound Pipeline - Systems Architecture Document

## 1. System Topology & LangGraph StateGraph

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

## 2. Directory Layout
```
outbound-pipeline/
├── data/
│   └── resume.json                 # Structured candidate highlights & placeholder contacts
├── pipeline/
│   ├── __init__.py
│   ├── state.py                    # PipelineState TypedDict definition
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract Adapter interfaces & Factory
│   │   ├── stub.py                 # Zero-network deterministic Stub adapters
│   │   └── live.py                 # Production Live adapters (Apollo/Phantom/Hunter/Gemini/Instantly)
│   ├── enrichment.py               # enrichment_node implementation
│   ├── drafting.py                 # drafting_node implementation & persona detection
│   ├── delivery.py                 # delivery_node staging implementation
│   └── graph.py                    # StateGraph construction & compilation
├── staged_deliveries/              # Destination directory for staged payloads
├── tests/
│   ├── __init__.py
│   └── test_pipeline.py            # Offline unit test suite with 100% pass guarantee
├── main.py                         # CLI entrypoint with runtime status banners
├── factory.py                      # 7-agent Autonomous Software Factory
├── Dockerfile                      # Production container spec
├── docker-compose.yml              # Local orchestration spec
├── .dockerignore
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## 3. Node Contracts & Functional Signatures

### 3.1 `enrichment_node(state: PipelineState) -> dict`
- **Input**: Current `PipelineState` dictionary containing `domain`.
- **Process**: Instantiates `EnrichmentAdapter` via `AdapterFactory.get_enrichment_adapter()`.
- **Output**: Dictionary updates: `{"contact_name": ..., "contact_email": ..., "contact_role": ...}`.
- **Contract Rule**: Never mutates `state` in-place. Returns only updated keys.

### 3.2 `route_after_enrichment(state: PipelineState) -> Literal["drafting_node", "skip_node"]`
- **Condition**: Evaluates `bool(state.get("contact_email"))` with regex format validation (`^[\w\.-]+@[\w\.-]+\.\w+$`).
- **Routing**: If valid, returns `"drafting_node"`. Otherwise returns `"skip_node"`.

### 3.3 `skip_node(state: PipelineState) -> dict`
- **Process**: Invoked when contact email is missing or invalid.
- **Output**: `{"delivery_status": "skipped_no_email"}`.

### 3.4 `drafting_node(state: PipelineState) -> dict`
- **Input**: `PipelineState` with `contact_role`, `domain`, `contact_name`, and `resume_context`.
- **Process**: Classifies role into persona (`security`, `ai_ml`, `hr_talent`), fetches bullets from `resume_context`, invokes `DraftingAdapter.draft()`.
- **Output**: `{"email_draft": str}`.

### 3.5 `delivery_node(state: PipelineState) -> dict`
- **Input**: Full `PipelineState` with completed draft.
- **Process**: Invokes `DeliveryAdapter.deliver()`. Formats webhook body, attaches opt-out footer, stages payload to `staged_deliveries/{domain}_{timestamp}.json`.
- **Output**: `{"delivery_status": "staged"}` (or `"sent"` if live confirmed).

## 4. Adapter Pattern Architecture
The adapter layer separates pipeline logic from external API integrations:
- `AdapterFactory` reads environment variables:
  - `APOLLO_MODE` / `ENRICHMENT_MODE`: `"stub"` (default) | `"live"`
  - `DRAFTING_MODE`: `"stub"` (default) | `"live"`
  - `DELIVERY_MODE`: `"stub"` (default) | `"live"`
- `StubAdapter` implementations provide realistic mock behaviors for instant zero-network execution and reliable unit testing.
- `LiveAdapter` implementations encapsulate production APIs, rate limiting, and fallback cascades.
