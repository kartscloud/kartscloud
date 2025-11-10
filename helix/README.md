# Helix – Blockchain Microstructure Platform

Helix is a SaaS platform that unifies on‑chain wallet movements, mempool intents and exchange order‑book data to provide predictive liquidity intelligence for crypto markets.

## Mission

Give traders and institutions predictive visibility into market liquidity before price moves by combining:
- **Mempool streams** for pending transactions and swaps
- **On‑chain wallet flows** from whales, bridges and issuers
- **Order‑book microstructure** from multiple venues (depth, trades, cancels)

## Core Idea

Helix listens to the earliest signals of capital flow and synchronizes them into a single data graph. By modelling lead‑lag relationships between wallets and venues, Helix forecasts liquidity shifts seconds before they hit exchanges. The platform exposes these insights via:
- **Helix Flow Tape** – a streaming API of flow events and liquidity metrics
- **Liquidity Bias Signals** – probabilistic indicators of buy/sell pressure and estimated latency
- **Graph‑based analytics** – entity clustering, venue routing, and liquidity stress scoring

## Why It’s Different

Existing vendors provide individual slices (on‑chain analytics, market data or mempool feeds). Helix fuses all three layers in real time and delivers machine‑readable feeds for execution desks. The data fusion layer is the core IP: a low‑latency graph that maps wallets to venues, aligns timestamps and predicts liquidity migration.

## Roadmap Highlights

1. **Foundation (0–6 mo):** MVP covering BTC/ETH on one exchange, 200 wallet clusters, mempool alerts. Achieve <10 s latency and 75 % prediction accuracy.
2. **Expansion (6–18 mo):** Multi‑chain/venue coverage, release Helix Flow Tape and Smart‑Money Liquidity Index. Aim for $1 M ARR with 20+ clients.
3. **Institutionalization (18‑30 mo):** Helix Execution API with OMS/EMS integrations and white‑label dashboards. Target $5‑10 M ARR with 50+ clients.
4. **Strategic Positioning (2.5‑4 yrs):** Cross‑asset analytics (FX, equities) and partnerships with major data platforms. Aim for $15‑25 M ARR.
5. **PE Readiness (4‑5 yrs):** Build a cash‑flowing data‑infrastructure company with $20 M+ ARR and 85 % gross margin.

## File Structure

This repository will contain:
- `helix/` – core documentation, architecture diagrams, and source code for the Helix platform
- Additional directories for data ingestion scripts, models, and dashboard code (to be added)

---

Helix is currently in the prototyping phase. Stay tuned for more updates and contributions!
