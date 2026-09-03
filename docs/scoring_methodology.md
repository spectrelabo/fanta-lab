# Composite Scoring Methodology — fanta-lab

The **Composite Score** in `fanta-lab` is a normalized synthetic metric in the range $[0.00, 1.00]$ designed to quantify a player's auction value by balancing historical consistency, projected productivity, physical reliability, and market efficiency.

---

## Mathematical Formulation

$$\text{Score}_{\text{base}} = \sum_{i} w_i \cdot \text{Norm}(F_i)$$

$$\text{Score}_{\text{final}} = \text{Score}_{\text{base}} \times \left(1.0 - 0.15 \times \text{Injury Malus}\right)$$

---

## Feature Weighting Scheme

| Feature ($F_i$) | Weight ($w_i$) | Description | Mathematical Objective |
|---|---|---|---|
| **Weighted Historical Rating (3y)** | `0.20` | Weighted 3-season average rating (decaying weights: $3\times, 2\times, 1\times$) | Eliminates variance from single-season outliers and rewards multi-year baseline performance. |
| **Expected Seasonal Rating** | `0.20` | Model-projected baseline rating for the upcoming season | Adjusts for current tactical role, team strength, and age curve. |
| **Expected Fantamedia** | `0.15` | Total projected fantasy average (baseline rating + bonus/malus) | Quantifies raw points-generating capacity. |
| **High Bonus Probability (>= 8)** | `0.20` | Probability density of registering match-winning performances (score >= 8.0) | Rewards high-ceiling match-winners over low-ceiling floor players. |
| **Expected Goals (xG) Average (3y)** | `0.10` | Three-year volume of Underlying Expected Goals | Identifies genuine shot volume and chance quality independent of finishing variance. |
| **Pitch Availability %** | `0.10` | Percentage of matchdays with rated appearances out of 38 fixtures | Penalizes squad rotation risks and tactical benchwarmers. |
| **Price Efficiency** | `0.05` | 1.0 - Norm(Price) (inversely proportional) | Yields a marginal boost to low-cost assets with elite underlying numbers. |

---

## Medical Risk & Injury Modeling

The injury malus parametrically reduces a player's final auction score by up to **15%** based on cumulative absence duration and severe injury history:

$$\text{Days Penalty} = \min\left(\frac{\text{Days Injured 3y}}{180}, 1.0\right)$$

$$\text{Severity Penalty} = \begin{cases} 0.30 & \text{if } \text{Max Single Absence} \ge 60 \text{ days} \\ 0.00 & \text{otherwise} \end{cases}$$

$$\text{Injury Malus} = \min\left(0.70 \cdot \text{Days Penalty} + \text{Severity Penalty}, 1.0\right)$$

### Strategic Auction Impact:
- **Ironman Assets** ($\text{Injury Malus} = 0.00$): Retain 100% of their theoretical statistical value.
- **High-Risk Fragile Assets** ($\text{Injury Malus} = 1.00$): Experience a non-negotiable 15% valuation cut, preventing overbidding on hospital regulars.

---

## Robust Min-Max Feature Scaling

Each continuous feature $X$ is scaled to the unit interval $[0, 1]$ via:

$$\text{Norm}(X) = \frac{X - \min(X)}{\max(X) - \min(X)}$$

Missing values ($NaN$) are imputed with neutral baseline priors (e.g., $0.75$ for availability, $0.0$ for advanced expected metrics for newly promoted or incoming foreign players).
