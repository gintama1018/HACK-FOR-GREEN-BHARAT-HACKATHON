# Risk Assessment Guidelines

## Infrastructure Risk Score Interpretation
The risk score (0-100) is a composite metric computed from 5 weighted factors:

| Factor | Weight | What It Measures |
|---|---|---|
| Citizen Reports | 25% | Density of hazard reports from citizens, field officers |
| Traffic Load | 20% | Vehicle volume × heavy vehicle percentage |
| Rainfall Stress | 20% | Rainfall intensity × drainage vulnerability |
| Accident Severity | 20% | Severity-weighted count of recent accidents |
| Permit Gap | 15% | Days since last active maintenance permit |

## State Definitions
- **Normal** (0-30): Infrastructure performing within acceptable limits. Routine monitoring.
- **Elevated** (31-55): Early signs of stress. Proactive inspection recommended.
- **Warning** (56-75): Significant degradation. Active intervention required.
- **Critical** (76-100): Immediate hazard. Emergency response mandated.

## Infrastructure Decay
Segments in Elevated+ state experience progressive condition degradation:
- Elevated: 0.05 points/cycle
- Warning: 0.15 points/cycle
- Critical: 0.30 points/cycle

This models real-world behavior: unaddressed problems accelerate.

## Prediction Model
Projected Risk Delta = rainfall × drainage_multiplier × traffic_factor × condition_factor × maintenance_factor
A positive delta indicates expected worsening.
