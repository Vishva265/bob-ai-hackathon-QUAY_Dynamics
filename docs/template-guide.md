# QUAY Project and Submission Guide

## 1. Purpose

This guide explains how QUAY's implementation and evidence fit the hackathon repository structure. Use the [main README](../README.md) for an introduction and the [setup guide](setup-guide.md) for runnable commands. Detailed implementation and verification references are maintained in `src/docs/`.

## 2. Documentation Map

| File | Content |
|---|---|
| [README.md](../README.md) | Project summary, features, technology stack, quick start, and limitations. |
| [problem-statement.md](problem-statement.md) | Port congestion context, affected users, operational need, and challenge objectives. |
| [solution-overview.md](solution-overview.md) | End-to-end workflow, user experience, design decisions, and IBM integration scope. |
| [architecture.md](architecture.md) | Components, data flow, planning conventions, security, and scalability. |
| [setup-guide.md](setup-guide.md) | Prerequisites, configuration, installation, execution, tests, and troubleshooting. |
| [src/docs/](../src/docs/) | Feature references, lifecycle details, measured evaluations, and verification reports. |

The top-level documents describe the current project. Some detailed references preserve earlier delivery phases; verify time-sensitive claims against current code and the relevant evidence artifact.

## 3. Source and Artifact Locations

The application workspace is `src/`. Backend code, database migrations, scripts, and tests live in `src/backend/`; the React dashboard and browser journeys live in `src/frontend/`. npm commands run from `src/`.

The portable synthetic seed is in `src/demo/seed/`. The launcher prepares local state under `src/artifacts/hackathon-demo/`. Recorded evaluation outputs and the offline presentation are in `src/demo/recorded/` and `src/demo/backup/`. Dashboard screenshots are in `src/docs/screenshots/`; presentation assets live in the top-level `presentation/` directory.

The top-level `demo/` directory contains submission link files and the screenshot submission location. These are separate from the application demo assets.

## 4. Submission Metadata

`submission.yaml` holds team identity, track, project title, summaries, features, technology choices, limitations, and artifact paths. Complete it with actual team information before submission. Required team and project fields are currently unfilled; the documentation does not supply invented identities.

Describe IBM use precisely. QUAY has an optional watsonx.ai / Granite explanation adapter and a BOB Operations Copilot interface. Existing evidence does not certify a live IBM response or a separate Bob CLI/MCP integration. Any claimed development use of IBM Bob should be supported by actual team evidence.

## 5. Demo Evidence

Record a concise end-to-end demonstration: start QUAY, inspect a hotspot, show berth/crane assignments, open the nine-shift plan, and explain supervisor review and approval. A live event and grounded copilot answer can show how changed conditions are handled.

Update `demo/demo-video-link.txt` with the hosted recording and `demo/live-demo-url.txt` with an actual deployment URL or an accurate local-only status. Both files currently contain template links. Use viewable sharing permissions and confirm the links independently.

For results, cite the exact evaluation used. The bundled September 13 recording and the newer report in `src/docs/` use different model versions and cohorts; do not combine their figures. Keep synthetic results, proxy savings, served demand, deferrals, and model weaknesses explicit.

## 6. Automated Validation

The existing `.github/workflows/validate.yml` checks required files, YAML parsing, required metadata, accepted track values, source presence, the video placeholder, and selected README placeholders. Review the workflow result after pushing an authorised submission update.

Structural validation does not prove model accuracy, feasible scheduling, production readiness, or working IBM connectivity. Use backend/frontend checks and recorded verification evidence for those claims.

## 7. Submission Checklist

- Complete actual team and submission fields in `submission.yaml`.
- Confirm a reviewer can run QUAY using `docs/setup-guide.md`.
- Replace hosted video and deployment template links.
- Provide accessible screenshots and the final presentation.
- Identify which evaluation and model version support impact claims.
- Verify the optional IBM provider before claiming a live integration.
- Keep credentials, virtual environments, dependencies, and generated local state out of commits.
- Confirm automated validation and the organiser's submission requirements.

The functional demo can run locally while submission metadata and hosted evidence are being completed.
