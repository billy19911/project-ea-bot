# TASK T4 — Remove false "premium/discount" claim + add zone classification (Python)

## Context (verified root cause — do NOT re-investigate)
- In a previous answer (msg 162404), the assistant claimed `structure_analyst.py` computes "premium/discount" zones. This is FALSE — `grep -inE "premium|discount|zone_type|premium_discount" structure_analyst.py` returns 0 hits.
- What ACTUALLY exists in `services/python/src/agents/analysts/structure_analyst.py`:
  - `_detect_market_structure_pattern` (:162) → BOS/CHoCH/sweep detection using swing highs/lows.
  - `_detect_fvg` (:228) → Fair Value Gap (imbalance) detection.
  - `_detect_order_blocks` (:336) → Order block detection.
  - `analyze()` (:418-560) → aggregation + signal construction.
  - Tests: `test_structure_analyst_smc_pattern_metadata` + 18/18 passed (commit `47fe221`).
- The actual SMC concept of "premium/discount" is: price above the 50% equilibrium of the current swing range = premium zone (sell bias); below = discount zone (buy bias). This is a standard SMC concept that SHOULD be implemented.

## Deliverable
Add a `_classify_zone` method to `StructureAnalyst` and wire it into `analyze()` output.

### 1. New method `_classify_zone` (in `structure_analyst.py`)
Place after `_detect_order_blocks` (after ~line 400):

```python
@staticmethod
def _classify_zone(
    current_price: float,
    swing_high: float,
    swing_low: float,
) -> dict:
    """Classify current price as premium, discount, or equilibrium zone."""
    if swing_high <= swing_low or swing_high <= 0:
        return {"zone": "unknown", "equilibrium": 0.0, "distance_pct": 0.0}
    eq = (swing_high + swing_low) / 2.0
    dist_pct = ((current_price - eq) / (swing_high - swing_low)) * 100.0
    if current_price > eq:
        zone = "premium"
    elif current_price < eq:
        zone = "discount"
    else:
        zone = "equilibrium"
    return {
        "zone": zone,
        "equilibrium": round(eq, 5),
        "distance_pct": round(dist_pct, 2),
    }
```

### 2. Wire into `analyze()` output
In `analyze()`, after the existing pattern/fvg/ob analysis and before the final return/signal construction (~line 500-530 where the result dict is built):

1. Extract `swing_high` and `swing_low` from the existing swing detection (`self._swing_high`, `self._swing_low` or from the `candles` highs/lows used by `_detect_market_structure_pattern` — check which attribute holds the most recent swing values).
2. Get current price from the last candle close.
3. Call `_classify_zone(current_price, swing_high, swing_low)`.
4. Add `"zone_classification"` key to the returned analysis dict.

### Shape of zone_classification in output
```python
{
    "zone_classification": {
        "zone": "premium" | "discount" | "equilibrium" | "unknown",
        "equilibrium": 2650.12345,
        "distance_pct": 15.3  # positive = premium, negative = discount
    }
}
```

### IMPORTANT: Find the actual swing values
Before implementing, grep/read `analyze()` to find how swing_high/swing_low are stored. The `_detect_market_structure_pattern` method computes swings — trace where it stores them (likely as `pattern["swing_high"]` / `pattern["swing_low"]` in its return dict, or as attributes). Use THOSE values — do not recompute from raw candles.

## Tests (TDD — write tests first, then implement)
New file `services/python/tests/test_zone_classification.py`.

Required cases:
1. Price above equilibrium → zone="premium", distance_pct > 0.
2. Price below equilibrium → zone="discount", distance_pct < 0.
3. Price at exact equilibrium → zone="equilibrium", distance_pct ≈ 0.
4. Invalid swing (high <= low) → zone="unknown".
5. Integration: `analyze()` output contains `zone_classification` key with correct shape.
6. Zone classification does not break existing SMC tests (run `test_structure_analyst*.py`).

Run SERIAL from `services/python`:
`services/python/.venv/Scripts/python.exe -m pytest tests/test_zone_classification.py tests/test_structure_analyst.py -q`

## Verify before finishing
- `services/python/.venv/Scripts/python.exe -m pytest tests/test_zone_classification.py tests/test_structure_analyst.py -q`
- `services/python/.venv/Scripts/python.exe -m flake8 src/agents/analysts/structure_analyst.py tests/test_zone_classification.py --max-line-length=100 --extend-ignore=E203,W503`
- `services/python/.venv/Scripts/python.exe -m black --line-length 100 <only your changed files>`

## Hard constraints
- Only edit: `services/python/src/agents/analysts/structure_analyst.py`, `services/python/tests/test_zone_classification.py` (new).
- Do NOT touch `services/python/src/config.py` or `services/python/src/main.py`.
- Do NOT reformat unrelated code; keep the diff minimal.
- Do NOT run restart scripts (`restart-py.ps1` / `restart-all.ps1` / `run_ops_drills.py`) and do NOT wait for services.
- Do NOT use `&` in shell commands. Do NOT commit.
- Report in your final message: files changed, exact test commands + results, and any deviation.
