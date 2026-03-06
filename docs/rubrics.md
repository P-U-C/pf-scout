# Rubrics

A rubric is a YAML file defining scoring dimensions.

## Structure
```yaml
name: My Rubric
version: "1.0"

dimensions:
  - id: quant_depth
    name: Quantitative Depth
    weight: 1.5          # weighted scoring multiplier
    description: ...
    score_guide:
      5: "..."
      4: "..."
      ...

tiers:
  top:         { label: "🔴 TOP",        min_pct: 0.64 }
  mid:         { label: "🟡 MID",        min_pct: 0.40 }
  speculative: { label: "⚪ SPECULATIVE", min_pct: 0.0  }
```

## Bundled rubrics
- `rubrics/b1e55ed.yaml` — b1e55ed producer fit (5 dimensions, weights 1.0–1.5)

## Versioning
Snapshots store `rubric_name + rubric_version`. If the rubric changes, old snapshots are flagged as incompatible in `pf-scout diff`.
