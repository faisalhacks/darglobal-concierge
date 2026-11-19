# Quality round: frozen interface contract

Frozen before any lane starts. Lanes may add fields behind these, never rename or drop one. A change needs the Integrate step, not a lane.
Source: quality council, `chair.lanes`. Owner overrides: playbook has 32 ids (see `evals/conversations_30.yaml` header); light mode is also re-toned.

## 1. Memory (owner: Lane B, `conversation.py` / `planner.carried_context()`)

```python
@dataclass
class Memory:
    site: str | None            # "DarGlobal" | "Wasalt" | None
    country: str | None         # canonical English name, as in the store
    city: str | None
    property_type: str | None   # villa | apartment | townhouse | land | floor | penthouse ...
    listing_type: str | None    # "buy" | "rent" | None
    beds: int | None
    budget_max: float | None
    currency: str | None        # ISO code ("SAR", "AED", "OMR" ...)
    last_entities: list[str]    # ids shown on the previous turn, order preserved, max 6
    last_intent: str | None
```

Rules (Lane B enforces, eval asserts):
- An explicit new value wins over the remembered one.
- A new country clears city.
- `reset: true` from understanding clears everything.
- Memory values never come from the client; only `last_entities` ids do, and those are validated against the store.
- `build_messages` receives a memory block (ids with names resolved from the store), not raw truncated turns.

## 2. ChatRequest.last_entities (owner: Lane C `chat.py`; sender: Lane D frontend)

```python
@dataclass
class ChatRequest:
    session_id: str
    message: str
    history: list[dict]
    lang: str = "auto"
    last_entities: list[str] = field(default_factory=list)   # NEW: ids only, max 6
```

Wire format: `POST /api/chat/stream` JSON body gains `"last_entities": ["dg-aida", "wasalt-p-100324"]`.
- Ids only, never names. Max 6; extra items are dropped, not an error.
- Each id is validated against the store (projects and listings). Unknown ids are dropped silently.
- Absent or empty is valid and means "no reference context".
- The frontend fills it from the ids of the last `cards` event (projects first, then listings, in card order).

## 3. Understanding output schema (owner: Lane B `understanding.py`)

The existing keys stay. Added or widened:

```json
{
  "intent": "search | project_info | ... | superlative",
  "sort": "price_asc | price_desc | area_desc | area_asc | newest | null",
  "refs": [1],
  "reset": false,
  "question_type": "factual | recommendation | comparison | chitchat | out_of_scope | ..."
}
```

- `intent` gains the value `"superlative"` ("most expensive villa", "cheapest in Riyadh", "largest", "newest").
- `sort` is one of exactly five values or null. A superlative plan must set it: most expensive = `price_desc`, cheapest = `price_asc`, largest = `area_desc`, smallest = `area_asc`, newest = `newest`.
- `refs` is a list of 1-based positions into `Memory.last_entities` ("the second one" gives `[2]`, "compare them" gives `[1, 2]`). Empty when no reference.
- `reset` is true when the user abandons the previous topic ("forget that, something else", a clear topic switch).
- `question_type` is a free-but-closed label used for playbook selection and trace; unknown values are mapped to `"factual"` by `validate()`.
- `validate()` still drops any extracted value that is not present in the store holdings (country, city, project names). Nothing invented survives.

## Eval-side invariants (so before/after runs are comparable)

- Same 30-conversation file, same provider (`EVAL_LLM_PROVIDER=nvidia`), same runner for both runs.
- The server reports per-request `trace.llm_calls`; the runner sums it against `EVAL_MAX_LLM_CALLS` (before 120, after 120, fix re-runs 30) and stops on quota.
- Production budgets (45/day, 200/day) are never touched by eval runs.
