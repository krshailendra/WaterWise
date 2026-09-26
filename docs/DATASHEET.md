# DATASHEET — WaterWise dataset (placeholder, completed in P13)

This datasheet describes every dataset WaterWise produces: row counts per
provenance class (`public_observed` / `modelled` / `synthetic`), collection
windows, cadence per source, retrieval dates, how AI was used, and known gaps
and biases.

It is filled in progressively as phases land and finalised in **P13**.

## Row counts per provenance class

_To be populated by the pipeline. Do not hand-edit counts._

| provenance | rows |
|---|---|
| public_observed | — |
| modelled | — |
| synthetic | — |

## Known gaps and biases (kept current)

- CPCB NWMP river data is published mostly as yearly min/max, not a daily series.
- Sentinel-2 has a monsoon cloud gap.
- GloFAS discharge is modelled, not gauged.
- The campus network and all tap residuals are simulated until the WTP shares logs.
