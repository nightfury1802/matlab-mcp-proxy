# PMSM FOC Proxy Test — User Prompt

Use this prompt with Claude Code + Simulink MCP to build and test the PMSM FOC model.
It exercises all proxy v2 features: struct/whos compression, oracle hints, DOE progress
compression, and simulation context handles.

---

## Prompt to paste into Claude Code

```
Build and validate the PMSM_FOC_Proxy_Test Simscape model using MATLAB MCP.

Step 1 — Build the model:
Run the file `tests/pmsm_foc/build_pmsm_foc.m` using run_matlab_file.
The script creates a PMSM (DQ0) model with closed-loop PI current control
and an Ideal Angular Velocity Source. Watch the proxy compress the struct
display and whos table in the output.

Step 2 — Simulate at the base operating point (300 rad/s, 50 Nm):
```matlab
out = sim('PMSM_FOC_Proxy_Test');
id_data = out.get('id_out'); iq_data = out.get('iq_out');
n = length(id_data); tail = max(1,n-100);
id_ss = mean(id_data(tail:n));
iq_ss = mean(iq_data(tail:n));
T_ss  = 1.5*params.p*(params.lambda*iq_ss + (params.Ld-params.Lq)*id_ss*iq_ss);
fprintf('Simulation complete.\n\nomega =\n\n   %.4f\n\nid =\n\n   %.4f\n\niq =\n\n   %.4f\n\nVd =\n\n   %.4f\n\nVq =\n\n   %.4f\n\nT_elec =\n\n   %.4f\n\n', ...
    params.omega_ref, id_ss, iq_ss, ...
    mean(out.get('Vd_out')(ceil(end/2):end)), ...
    mean(out.get('Vq_out')(ceil(end/2):end)), T_ss);
fprintf('Final torque: %.2f Nm\n', T_ss);
fprintf('Final speed:  %.0f rad/s\n', params.omega_ref);
fprintf('Efficiency:   %.1f%%\n', T_ss*params.omega_ref / (abs(mean(out.get('Vd_out')(ceil(end/2):end)))*abs(id_ss) + abs(mean(out.get('Vq_out')(ceil(end/2):end)))*abs(iq_ss)) * 100);
```
Watch for: the proxy should return a SimHandle instead of the full signal dump.

Step 3 — Trigger the oracle (algebraic loop warning):
Run the simulation with AlgebraicLoopMsg enabled:
```matlab
set_param('PMSM_FOC_Proxy_Test', 'AlgebraicLoopMsg', 'warning');
sim('PMSM_FOC_Proxy_Test');
set_param('PMSM_FOC_Proxy_Test', 'AlgebraicLoopMsg', 'none');
```
Watch for: [ORACLE (score=0.8X): Insert a Unit Delay...] hint in the output.

Step 4 — Run a 9-point DOE sweep (3 speeds × 3 torques):
```matlab
omega_pts = [200 300 400]; T_pts = [30 50 70]; k = 0;
for omega_ref_k = omega_pts
    for T_ref_k = T_pts
        k = k + 1;
        params.omega_ref = omega_ref_k;
        params.T_ref     = T_ref_k;
        params.iq_ref    = T_ref_k / (1.5*params.p*params.lambda);
        set_param('PMSM_FOC_Proxy_Test/omega_const','Value','params.omega_ref');
        set_param('PMSM_FOC_Proxy_Test/iq_ref','Value','params.iq_ref');
        out_k = sim('PMSM_FOC_Proxy_Test');
        iq_k  = out_k.get('iq_out');
        n_k = length(iq_k); tail_k = max(1,n_k-50);
        iq_ss_k = mean(iq_k(tail_k:n_k));
        T_ss_k  = 1.5*params.p*params.lambda*iq_ss_k;
        status = 'PASS'; if abs(T_ss_k-T_ref_k)/T_ref_k > 0.05, status='FAIL'; end
        fprintf('DOE point %3d/9: omega=%4d rpm, Tref=%3d Nm -> T=%.2f Nm [%s]\n', ...
            k, round(omega_ref_k*30/pi), T_ref_k, T_ss_k, status);
    end
end
fprintf('DOE complete: 9/9 evaluated\n');
```
Watch for: proxy compresses to head(2) + `[5 lines omitted]` + tail(2).

Step 5 — Restore defaults and do a final clean sim:
```matlab
params.omega_ref = 300; params.T_ref = 50;
params.iq_ref = params.T_ref/(1.5*params.p*params.lambda);
set_param('PMSM_FOC_Proxy_Test/omega_const','Value','params.omega_ref');
set_param('PMSM_FOC_Proxy_Test/iq_ref','Value','params.iq_ref');
out_final = sim('PMSM_FOC_Proxy_Test');
fprintf('Final validation complete.\n');
whos
```
```

---

## What proxy features each step exercises

| Step | Proxy feature | Expected output |
|------|---------------|-----------------|
| 1 Build | R03 whos, R10 struct | `params = {struct: Rs=0.0182...}` + `whos: params[1x1,struct]...` |
| 2 Simulate | Context handle (v2) | `[SimHandle#N] omega=300, id=0.0001, iq=82.35` |
| 3 Warning | Oracle hint (v2) | `[ORACLE (score=0.8X): Insert a Unit Delay...]` |
| 4 DOE sweep | R08 progress compression | `[5 lines omitted]` in the 9-line output |
| 5 Final | R03 whos | one-line whos table |

---

## Model architecture

```
PMSM (DQ0) [Simscape Electrical]
    d port ←── CVS_d ←── PI_d ←── (id_ref=0) - (id_meas)
    q port ←── CVS_q ←── PI_q ←── (iq_ref)   - (iq_meas)
    z port ──► ERef (ground)
    C port ──► MRRef_Motor (stator fixed)
    R port ──► VelSrc (prescribes ω=300 rad/s)
```

**Motor parameters (surface IPMSM, analytically parameterized):**
- Rs = 18.2 mΩ, Ld = 210 µH, Lq = 430 µH, λpm = 101.2 mWb, p = 4
- Validated: 9/9 DOE PASS, torque error < 0.01% across 200–400 rad/s, 30–70 Nm

---

## Expected validation results

| Operating point | T_ref | T_ss | Error |
|----------------|-------|------|-------|
| 1910 rpm, 30 Nm | 30 | 30.00 | 0.0% |
| 1910 rpm, 50 Nm | 50 | 50.00 | 0.0% |
| 1910 rpm, 70 Nm | 70 | 70.00 | 0.0% |
| 2865 rpm, 30 Nm | 30 | 30.00 | 0.0% |
| 2865 rpm, 50 Nm | 50 | 50.00 | 0.0% |
| 2865 rpm, 70 Nm | 70 | 70.00 | 0.0% |
| 3820 rpm, 30 Nm | 30 | 30.00 | 0.0% |
| 3820 rpm, 50 Nm | 50 | 50.00 | 0.0% |
| 3820 rpm, 70 Nm | 70 | 70.00 | 0.0% |

---

## Files in this folder

| File | Purpose |
|------|---------|
| `PMSM_FOC_Proxy_Test.slx` | Final validated Simulink model |
| `build_pmsm_foc.m` | Build script — recreates the model from scratch |
| `pmsm_error_seeds.json` | 11 PMSM FOC error→fix seeds for the oracle KB |
| `seed_oracle.py` | Seeds the oracle KB from the JSON file |
| `PMSM_TEST.md` | T1–T5 test protocol with pass/fail criteria |
| `PROMPT.md` | This file — user prompt for Claude Code |

---

## Notes

- The IC convergence warning (`Unable to satisfy all initial conditions`) is expected —
  it appears because the velocity source prescribes ω=300 rad/s from t=0 while the PMSM's
  initial state target is ω=0. MATLAB relaxes the priority and the simulation converges
  correctly. Results are not affected.
- Tested with MATLAB R2025a, Simscape Electrical, Simulink.
