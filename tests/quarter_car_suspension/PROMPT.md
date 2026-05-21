# Quarter-Car Active Suspension — Original Prompt

## Prompt used to generate QCar.slx / QCarV2.slx

> "I want to build a Quarter-Car Active Suspension system. Please use the MATLAB MCP tools to write a script that opens a new Simulink model, loads the Simscape Foundation library, creates a mass-spring-damper system representing a car chassis and wheel, adds a controlled force actuator for active control, and wires up a basic feedback loop. Set the vehicle mass parameter to 400kg."

## Success Metrics

> Your test is successful if:
>
> 1. **Zero-Click Generation:** Claude successfully creates the `.slx` file and populates it with blocks via MCP commands.
> 2. **Simulation Runs:** You can type `sim('model_name')` in MATLAB and it executes without data-type or solver errors.
> 3. **Performance Check:** The active system settles back to equilibrium faster than a purely passive system when hitting the road bump.

## What was actually built

- **QCar.slx** — first version, built entirely via `mcp__matlab__evaluate_matlab_code` + Simscape API
- **QCarV2.slx** — rebuilt from scratch using `mcp__simulink__model_edit` (Simulink Agentic Toolkit)

Both models share the same physical topology:

```
Ground ── TyreSpring (kt=190,000 N/m) ── WheelMass (40 kg)
                                              │
                          ┌───────────────────┼───────────────────┐
                    SuspSpring          SuspDamper            Actuator
                    ks=16,000 N/m       cs=1,400 Ns/m         (PD control)
                          └───────────────────┼───────────────────┘
                                              │
                                        ChassisMass (400 kg)
```

Controller: PD on absolute chassis velocity  
`F_act = −(Kp · v_chassis + Kd · dv/dt)`  where Kp=8000, Kd=800

Road input: 4,000 N pulse, 0.1 s duration, at t = 0.5 s

## Results

| | Passive | Active |
|---|---|---|
| Peak chassis velocity | 0.120 m/s | 0.046 m/s |
| Settling time (2% threshold) | 2.665 s | 1.761 s |
| Peak reduction | — | **61.7%** |
| Settling speedup | — | **33.9%** |

All three success metrics were met.
