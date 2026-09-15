# 🚀 QUAY — Container Congestion Predictor & Port Operations Optimiser

> An intelligent port operations decision-support system predicting congestion hotspots up to 72 hours in advance, optimising joint berth and crane allocations with Google OR-Tools CP-SAT, and delivering auditable shift plans with IBM watsonx.ai & Granite Copilot.

---

## 👥 Team

| Field | Value |
|---|---|
| **Team Name** | QUAY_Dynamics |
| **Track** | AI |
| **Team Lead** | Jay Patel — 23dcs076@charusat.edu.in |
| **Members** | Vishva Valand (23dcs140@charusat.edu.in), Mahi Patel (23dcs081@charusat.edu.in), Vasu Vaghasia (23dcs138@charusat.edu.in) |

---

## 🎯 Problem Statement

> In 2–3 sentences: What problem does your project solve? Who experiences this problem?

The 2021–2022 LA/Long Beach port backlog stranded over 100 container vessels offshore, costing global supply chains over $10B. Today, port operators still coordinate berths, cranes, and yard space across hundreds of vessels manually in static spreadsheets, discovering congestion hotspots reactively after queues form when alternate routing decisions are too late. This lack of advance visibility leaves terminal planners, shift supervisors, and shipping operators unable to anticipate cascading bottlenecks or evaluate feasible operational responses.

---

## 💡 Solution

> In 2–3 sentences: What did you build? How does it solve the problem above?

QUAY is an intelligent port operations decision-support system that predicts congestion hotspots up to 72 hours in advance, recommends alternate routing strategies, and optimizes joint berth and crane assignments using Google OR-Tools CP-SAT. It automatically synthesizes auditable 72-hour rolling shift plans (9 consecutive 8-hour shifts) with actionable handover notes, and integrates an evidence-grounded BOB Operations Copilot (powered by IBM watsonx.ai & Granite) with real-time SSE replanning to keep human supervisors firmly in command.

---

## ✨ Key Features

- **Predictive Congestion Forecasting:** Generates hourly hotspot and vessel waiting predictions over a 72-hour rolling horizon using versioned scikit-learn models and physical FIFO resource projections across berths, cranes, and yards.
- **Joint Berth & Crane Optimisation:** Solves complex multi-resource scheduling via Google OR-Tools CP-SAT, enforcing vessel draft, length, crane outreach/capacity, tidal clearances, and yard thresholds on a 15-minute grid with independent mathematical validation.
- **Alternate Routing & What-If Engine:** Evaluates arrival speed adjustments (slow-steaming), terminal transfers, and alternate ports with transparent cost, carbon emissions, and receiving-capacity trade-offs.
- **72-Hour Rolling Supervisor Shift Plans:** Produces 9 consecutive 8-hour supervisor shift plans complete with work orders, contingency actions, and exportable JSON, CSV, and printable HTML formats.
- **BOB Operations Copilot & Live Replanning:** Provides evidence-grounded operational reasoning with an IBM watsonx.ai / Granite adapter, real-time Server-Sent Events (SSE) live operations replanning, and immutable audit logs.

---

## 🛠️ Tech Stack

| Category | Technologies |
|---|---|
| **Languages** | Python 3.12, TypeScript |
| **Frameworks** | FastAPI, React 18, Vite |
| **IBM Technologies** | watsonx.ai, Granite (granite-13b-chat-v2 / granite-3-8b-instruct), IBM Bob |
| **Databases** | SQLite (Development/Demo), PostgreSQL (Production), SQLAlchemy |
| **Other** | Google OR-Tools (CP-SAT), scikit-learn, Docker, Leaflet, Recharts, Pydantic |

---

## 📁 Repository Structure

```
├── src/                  # All source code (FastAPI backend & React Vite frontend)
├── docs/                 # Written documentation & architectural specifications
│   ├── problem-statement.md
│   ├── solution-overview.md
│   ├── architecture.md
│   └── setup-guide.md
├── demo/                 # Demo artifacts and verification links
│   ├── screenshots/      # App screenshots and visual journey
│   ├── demo-video-link.txt  # Link to hosted demo video
│   └── live-demo-url.txt    # Deployed demo URL / local run status
├── presentation/         # Slide deck (slides.pptx & demo-deck.pptx)
└── submission.yaml       # Structured submission metadata
```

---

## ⚡ How to Run

> **Copy these exact steps from your [`docs/setup-guide.md`](docs/setup-guide.md)**

```bash
# 1. Clone the repo
git clone https://github.com/Vishva265/bob-ai-hackathon-QUAY_Dynamics.git
cd bob-ai-hackathon-QUAY_Dynamics

# 2. Navigate to application workspace
cd src

# 3. Install dependencies & launch demo (one command setup for backend & frontend)
npm run demo

# 4. Access the application
# - Dashboard: http://127.0.0.1:5173
# - Interactive API docs: http://127.0.0.1:8000/docs
# - Operator access key: quay-local-demo-only-operator-key-2026
```

---

## 🖥️ Demo

| Artifact | Link |
|---|---|
| 📹 Demo Video | [Google Drive Demo Video](https://drive.google.com/drive/folders/1fd9_3cZgkCq7H6w2MC0AHjbCqoAoA3oh?usp=sharing) (see [demo/demo-video-link.txt](demo/demo-video-link.txt)) |
| 🌐 Live Demo | NOT DEPLOYED — run locally using [docs/setup-guide.md](docs/setup-guide.md) (see [demo/live-demo-url.txt](demo/live-demo-url.txt)) |
| 🖼️ Screenshots | [See demo/screenshots/](demo/screenshots/) (and [src/docs/screenshots/](src/docs/screenshots/)) |
| 📊 Presentation | [See presentation/slides.pptx](presentation/slides.pptx) (also [presentation/demo-deck.pptx](presentation/demo-deck.pptx)) |

---

## ⚠️ Known Limitations

> Be honest — judges appreciate transparency over overclaiming.

- **Synthetic Port Datasets & Simulation Proxies:** Evaluation and testing currently rely on reproducible synthetic port datasets (4 fictional ports) and simulation proxies for bunker costs and carbon emissions rather than live port telemetry.
- **Production TOS & AIS Ingestion:** Live AIS vessel tracking feeds and bidirectional synchronization with production Terminal Operating Systems (TOS) are outside the current hackathon scope and remain future work.
- **IBM Cloud Credentials for Live Watsonx:** The IBM watsonx.ai / Granite LLM reasoning adapter requires user-provided IBM Cloud IAM credentials; an evidence-grounded deterministic local fallback is used when API credentials are unset.

---

## 🏅 What We're Most Proud Of

The auditable end-to-end integration: instead of treating AI as an opaque black box, QUAY unites mathematical constraint guarantees (Google OR-Tools CP-SAT with independent validation) with machine learning forecasts and an evidence-grounded BOB Operations Copilot. By safeguarding active vessel operations and near-term commitments during live replanning, it empowers shift supervisors with 1-click approvals, transparent handover logs, and actionable contingency plans.

---
