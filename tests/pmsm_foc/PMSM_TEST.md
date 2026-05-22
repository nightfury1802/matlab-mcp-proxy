# PMSM FOC Proxy v2 Test Protocol

## Model
`PMSM_FOC_Proxy_Test` built by `build_pmsm_foc.m`
- Simscape Electrical PMSM (3-phase, analytical params: Rs=18.2mΩ, Ld=210µH, Lq=430µH)
- Averaged d/q voltage sources (simplified inverter)
- Discrete PI current control (Ts=100µs)
- 400V DC bus

## Prerequisites

1. MATLAB MCP proxy active with v2 features (branch: `proxy-improvements-v2`)
2. Oracle seeded: `python3 tests/pmsm_foc/seed_oracle.py`
3. MATLAB working dir set to the folder containing `PMSM_FOC_Proxy_Test.slx` (or run `build_pmsm_foc.m` first)

---

## T1: Build model — whos + struct compression

**Run:** `evaluate_matlab_code` with contents of `build_pmsm_foc.m`

**Expected compressed output contains:**
- `whos: params[1x1,struct]  ...` (one-line whos table — R03)
- `params = {struct: Rs=0.0182, Ld=0.00021, ...}` (inline struct — R10)
- `### Built: PMSM_FOC_Proxy_Test` (build summary line — R07)

**Must NOT contain:** full whos table with `Bytes  Class` header row

---

## T2: Normal simulation → Context Handle

**Run:** `run_matlab_file` on `run_pmsm_foc_sim.m` (or Phase 1 section only)

**Expected proxy output:**
```
SimHandle#0: [model=PMSM_FOC_Proxy_Test] torque=107.XX, speed=XXX.X, ...
  -> Ask 'expand SimHandle#0' for full signal data.
```

**Must NOT contain:** full multi-line simulation dump

**Token count check:** output should be < 100 chars (vs ~500+ raw)

**Then test expansion:**
Ask Claude: "expand SimHandle#0"
Expected: full simulation output including all signals

---

## T3: Derivative error → Oracle hint

**Trigger:** Phase 2 of `run_pmsm_foc_sim.m` (sets Rs=0, collapses RL circuit)

**Expected proxy output:**
```
[ORACLE (score=0.9X): Set solver absolute tolerance to 1e-6. Verify Rs > 0...]
Error using sim (line ...)
Derivative of state '...' is not finite...
```

**Must contain:** `[ORACLE` prefix before the error
**Must NOT contain:** "An error occurred while running the simulation and the simulation was terminated:"

---

## T4: RCOND warnings → dedup + Oracle

**Trigger:** Phase 3 of `run_pmsm_foc_sim.m` (5 near-singular matrix solves)

**Expected proxy output:**
```
[ORACLE (score=0.8X): Check motor impedance parameters: if Ld/Lq are in mH...]
Warning: Matrix is close to singular or badly scaled. RCOND = 2.3e-17.
> In run_pmsm_foc_sim (line XX)  [x5]
```

**Must contain:** `[x5]` (dedup count) AND `[ORACLE` hint
**Must NOT contain:** 5 separate identical warning blocks

---

## T5: DOE progress → line compression

**Run:** `run_matlab_file` on `run_pmsm_foc_doe.m`

**Expected compressed output:**
```
DOE point   1/15: omega=1000 rpm, Tref= 50 Nm -> T=50.XX Nm [PASS]
DOE point   2/15: omega=1000 rpm, Tref= 80 Nm -> T=80.XX Nm [PASS]
  ... [11 lines omitted]
DOE point  14/15: omega=6000 rpm, Tref= 80 Nm -> T=XX.XX Nm [PASS]
DOE point  15/15: omega=6000 rpm, Tref=107 Nm -> T=XX.XX Nm [PASS]
```

**Must contain:** `lines omitted`
**Must NOT contain:** `DOE point   5/15` through `DOE point  13/15`

---

## Pass/Fail Summary

| Test | Must contain | Must NOT contain |
|------|-------------|-----------------|
| T1 | `whos:`, `{struct:` | `Bytes  Class` header |
| T2 | `SimHandle#`, signal values | Full multi-line sim dump |
| T3 | `[ORACLE`, error message | "An error occurred while running" |
| T4 | `[ORACLE`, `[x5]` | 5 identical warning blocks |
| T5 | `lines omitted` | `DOE point   5/15` |

---

## Adding new errors to the oracle

After any debugging session where you solve a new Simscape error, seed it so future runs get instant hints:

```python
from kb.error_oracle import ErrorOracle
oracle = ErrorOracle(store_dir='kb_store/')
oracle.learn(
    "Paste the exact MATLAB error message here",
    "Describe what fixed it — solver settings, parameter values, block changes"
)
print(f"KB size: {oracle.size()}")
```

Current KB size: 8 entries (PMSM FOC seeds from `seed_oracle.py`)
