# Northstar Components — Industrial Equipment Monitoring & Predictive Maintenance System

A portfolio project demonstrating skills in industrial data systems, Python backend
engineering, REST API design, and AVEVA PI System integration.  Built for a fictional
small manufacturing plant called **Northstar Components**.

---

## Plant Assets

| Asset ID  | Name                  | Type        | Sensors |
|-----------|-----------------------|-------------|---------|
| PUMP-001  | Cooling Water Pump    | pump        | temperature, flow_rate, inlet_pressure, outlet_pressure |
| MOTOR-001 | Main Drive Motor      | motor       | temperature, vibration, current, rpm |
| COMP-001  | Air Compressor        | compressor  | temperature, discharge_pressure, inlet_pressure, power_draw |

---

## Operating Modes

| Mode | Description |
|------|-------------|
| **Demo** | Fully self-contained.  No external dependencies, no license, no internet connection.  Uses a deterministic simulator with configurable fault scenarios. |
| **PI Integration** | Connects to an AVEVA PI Web API endpoint.  Requires valid credentials and network access.  Never represents synthetic data as PI data. |

---

## Project Structure

```
northstar/
├── backend/
│   ├── app/
│   │   ├── models/
│   │   │   ├── asset.py          # Asset & tag dataclasses
│   │   │   └── measurement.py    # Pydantic Measurement model
│   │   └── simulator/
│   │       ├── assets.py         # Asset registry
│   │       ├── ranges.py         # Operating ranges & thresholds
│   │       ├── scenarios.py      # Fault scenario definitions
│   │       └── engine.py         # Deterministic measurement generator
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_models.py
│   │   └── test_simulator.py
│   ├── pyproject.toml
│   └── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

*(Phases 2–8 will add `alembic/`, `app/api/`, `app/alert_engine/`, `frontend/`, `docker-compose.yml`, etc.)*

---

## Quick Start (Phase 1 — Simulator only)

### 1. Clone and enter the project
```bash
git clone <repo-url>
cd "Industrial Equipment Monitoring & Predictive Maintenance System"
```

### 2. Create and activate a virtual environment
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the automated test suite
```bash
pytest tests/ -v
```

Expected: **41 passed** in < 1 s.

### 5. Run the simulator smoke test
```bash
python -m app.simulator.engine
```

Prints 6 sample measurements per scenario showing tag values, engineering units,
and data quality codes.

---

## Fault Scenarios

| Scenario name    | Affected asset | What happens |
|------------------|---------------|--------------|
| `normal`         | All           | Baseline Gaussian noise within nominal range |
| `pump_overheat`  | PUMP-001      | Bearing temperature drifts toward 80 °C+ (lubrication failure) |
| `motor_vibration`| MOTOR-001     | Radial vibration spikes above ISO 10816 warning limit |
| `comp_pressure`  | COMP-001      | Discharge pressure climbs past 9.5 bar (downstream blockage) |
| `sensor_fault`   | All           | 40% of readings return BAD or NO_DATA quality |

All scenarios are **deterministic**: the same `SIM_SEED` always produces the same
sequence of measurements.  Set `SIM_SEED` in `.env` to replay a specific incident.

---

## Data Quality Codes

Matching OSIsoft PI System quality vocabulary:

| Code       | Meaning |
|------------|---------|
| `GOOD`     | Value is reliable and within nominal instrument range |
| `UNCERTAIN`| Value may be valid; instrument health is questionable |
| `BAD`      | Instrument reported an error; do not use for decisions |
| `NO_DATA`  | No measurement received within the expected polling window |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

| Variable           | Default   | Description |
|--------------------|-----------|-------------|
| `DATA_SOURCE`      | `demo`    | `demo` or `pi` |
| `SIM_SEED`         | `42`      | PRNG seed for reproducible demo data |
| `SIM_SCENARIO`     | `normal`  | Scenario name (see table above) |
| `SIM_POLL_INTERVAL`| `5`       | Seconds between generated measurements |
| `DATABASE_URL`     | —         | PostgreSQL async URL (Phase 2+) |
| `PI_BASE_URL`      | —         | PI Web API base URL (Phase 6+) |
| `PI_USERNAME`      | —         | PI Web API username |
| `PI_PASSWORD`      | —         | PI Web API password |
| `PI_VERIFY_SSL`    | `true`    | Verify TLS certificate |

---

## Architecture (Phase 1)

```
┌────────────────────────────────────────────┐
│               SimulatorEngine              │
│  seed + ScenarioConfig → Measurement[]     │
│                                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │ PUMP-001 │  │MOTOR-001 │  │ COMP-001 │ │
│  └──────────┘  └──────────┘  └──────────┘ │
└────────────────────────────────────────────┘
          │  produces
          ▼
┌─────────────────────────┐
│   Measurement (Pydantic)│
│  asset_id, tag_name,    │
│  value, unit, quality,  │
│  source, timestamp (UTC)│
└─────────────────────────┘
```

Phases 2–8 will add:
- PostgreSQL persistence layer (Phase 2)
- Alert engine with threshold rules (Phase 3)
- FastAPI REST endpoints (Phase 4)
- React dashboard (Phase 5)
- AVEVA PI Web API adapter (Phase 6)
- Docker Compose + full demo (Phase 7)

---

## PI System Integration Status

**Not yet connected to a live PI System.**

The PI adapter (Phase 6) is designed to connect to an AVEVA PI Web API endpoint when
`DATA_SOURCE=pi` and PI credentials are provided.  Integration tests use mocked HTTP
responses.  The application will **never** present synthetic data as PI data — the
`DataSource` field on every `Measurement` distinguishes `SIMULATED` from `PI_SYSTEM`.

---

## Development Notes

- Python 3.10+ required (tested on 3.10.13).
- `random.Random(seed)` — a local PRNG instance — is used instead of the module-level
  `random` functions so the global state is never modified.  Multiple simulators can
  run concurrently with independent seeds.
- Values are clamped to ±50% of the critical range to prevent physically impossible
  readings (e.g. negative pressure after many drift steps).
- Alert thresholds in `ranges.py` are based on typical published specifications for
  similar equipment and are illustrative, not certified engineering data.
