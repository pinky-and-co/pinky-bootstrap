---
paths:
  - "**/*.py"
  - "**/stored_procedures/**"
  - "**/tasks/**"
_load_conditions:
  - "if you are writing, modifying or reviewing Snowpark code, a stored procedure or a task, following the pinky pattern"
---
# Snowpark conventions — pinky pattern

Extends the public `snowpark.md` (session handling, DataFrame conventions) with the pinky SP
handler signature and its environment resolution / telemetry pattern.

## Stored procedure handler

```python
def main(session: snowpark.Session, args: dict = {}) -> dict | list:
```

- Always type-annotated
- `args` defaults to `{}` — never assume it's populated
- Return type is a `dict` (single result) or `list[dict]` (multiple files/batches)
- Wrap the body in `try/except Exception`, re-raise after setting `status = "error"` for
  `sp_trace()` (below) — **not** for logging or cleanup. A SQL error is already traced
  automatically by the platform per the configured `LOG_LEVEL`, and there is no temp
  file/connection state to clean up in this managed runtime. The `try/except` exists solely to
  let `sp_trace()` see the outcome before the exception propagates.

## Environment resolution

- Resolve environment via `get_environment()` from `pinky_snowpark`:
  ```python
  from pinky_snowpark.session import get_environment, EnvPattern

  v_env: str = get_environment(session, EnvPattern.ACCOUNT)
  ```
  Pinky convention: `EnvPattern.ACCOUNT` (one account = one env). Default: `EnvPattern.DATABASE_SUFFIX` (retro-compat).
  The pattern is chosen by the caller — do not hard-code a single detection strategy.

  | `EnvPattern` | Example |
  |---|---|
  | `DATABASE_SUFFIX` *(default)* | `MY_DB_SANDBOX` → `SANDBOX` |
  | `DATABASE_PREFIX` | `SANDBOX_MY_DB` → `SANDBOX` |
  | `SCHEMA_SUFFIX` | `MY_SCHEMA_QA` → `QA` |
  | `SCHEMA_PREFIX` | `QA_MY_SCHEMA` → `QA` |
  | `ACCOUNT` | account boundary — multi-account pinky convention |

## Argument resolution — `load_kwargs()`

SPs receive args either directly or via a Snowflake Task DAG (`_TASK_NAME$key` prefixed keys).
Use `load_kwargs()` from `pinky_snowpark` to normalise both transparently:

```python
from pinky_snowpark import load_kwargs, sp_trace


def main(session: snowpark.Session, args: dict = {}) -> dict:
    args = load_kwargs(
        args,
        required_keys={"run_date"},
        optional_keys={"env"},
    )
    # args is now {"run_date": ..., "env": ...} regardless of call origin
```

- `required_keys` — raises `ValueError` if missing after resolution
- `optional_keys` — resolved if present, ignored if absent
- `resolution` — force a specific origin when the same key appears under multiple prefixes
- `load_kwargs()` emits `sp_start` telemetry and sets span attributes automatically

## Return pattern and telemetry — `sp_trace()`

Do **not** use `SYSTEM$SET_RETURN_VALUE`. SPs are decoupled from Tasks. Accumulate results
step-by-step and emit telemetry at exit via `sp_trace()`:

```python
def main(session: snowpark.Session, args: dict = {}) -> dict:
    args = load_kwargs(args, required_keys={"run_date"})

    v_result: list = []
    v_return_values: dict = {}
    status = "ok"

    try:
        # … SP logic …
        rows = df.write.save_as_table(...).rows_updated
        v_result.append({"rows_updated": rows})
        v_return_values["continue"] = rows > 0

        return {"continue": 1, "return_values": v_return_values}

    except Exception:
        status = "error"
        raise

    finally:
        sp_trace(v_result, v_return_values, status=status)
```

- `v_result` — list of step dicts accumulated during execution (each step = one `append`)
- `v_return_values` — final business dict surfaced to the caller
- `sp_trace()` emits `sp_end` telemetry with flat span attributes — directly queryable in EVENT_TABLE
- `"continue"` key in the return dict signals DAG continuation without coupling to Tasks
- Set `status = "error"` in the `except` block before re-raising — `sp_trace()` picks it up
