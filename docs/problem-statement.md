# Problem Statement

## Background

Container ports connect ocean transport to terminal handling, storage, and inland delivery. Their effective capacity depends on several resources working together: an available berth needs compatible cranes, safe operating conditions, and enough yard space to receive cargo. Vessel arrival surges or equipment failures can therefore create queues even when another resource appears underused.

The hackathon challenge draws on the Los Angeles and Long Beach disruption that developed during 2021 and continued into 2022. The Marine Exchange of Southern California recorded a peak backlog of **109 container ships on 9 January 2022**, illustrating the scale of the planning problem. [LA/LB Harbor Safety Committee meeting minutes, October 2022](https://mxsocal.org/assets/pdf/hsc/minutes/189-hsc-minutes.pdf).

## The Problem

The challenge describes port operators coordinating hundreds of vessels through manually maintained spreadsheets. Schedules, berth capacity, crane outages, and yard conditions are difficult to reconcile as one constrained plan. Hotspots are identified reactively, after vessels are already queuing, while alternate routing decisions arrive too late to prevent avoidable delay.

The central problem is the gap between identifying future pressure and producing an actionable response. A warning must show where and when congestion is expected, what evidence supports it, and which operational changes are feasible. A revised plan must also respect work already underway and give the next supervisor a clear handover.

## Who Is Affected

| User | Operational need |
|---|---|
| Port and terminal planners | Allocate berth windows, cranes, and yard capacity across competing vessel calls. |
| Shift supervisors | Understand the next shift's work, shortages, alerts, contingencies, and handover responsibilities. |
| Vessel operators and shipping lines | Compare arrival adjustments or alternate destinations before committing to changes. |
| Operations managers | Assess throughput, waiting, deferred demand, resource use, and schedule stability together. |

Cargo owners and inland logistics providers are affected by downstream uncertainty, although QUAY's current interface focuses on planning and supervision.

## Why It Matters

Late congestion decisions can increase vessel waiting, disrupt cargo delivery, and intensify terminal storage pressure. The Port of Los Angeles' October 2021 response explicitly linked clearing containers from terminals with making room for waiting ships, demonstrating that berth queues and yard conditions are connected. [Port of Los Angeles cargo-clearing announcement](https://portoflosangeles.org/references/2021-news-releases/news_102931_cargofee).

QUAY aims to improve advance visibility and the quality of planning decisions. Its economic and emissions estimates use stated simulation assumptions; the project does not measure the historical disruption's total financial cost or establish realised savings at a working port.

## Why Existing Solutions Fall Short

Within the challenge's spreadsheet-based workflow, manual planning makes it difficult to compare interacting resource constraints or keep successive shifts aligned. A congestion dashboard alone leaves the allocation problem unresolved. A routing suggestion also needs receiving capacity, travel time, cargo compatibility, and commercial permission before it can become operationally useful.

QUAY combines forecasts, independently checked schedules, conditional routing comparisons, and a versioned supervisor publication. This integration is the project's response to the challenge; it is not a claim that existing commercial port systems lack these capabilities.

## Challenge and Project Objectives

> Build a Bob solution that predicts congestion hotspots using vessel schedules and berth capacity data, recommends alternate routing strategies, optimises berth and crane assignments, and generates a 72-hour port operations plan for shift supervisors.

The project translates this requirement into four deliverables: hourly hotspot forecasts, evidence-backed routing what-ifs, constrained berth/crane schedules, and nine eight-hour supervisor shifts. Operators retain approval authority. The current implementation demonstrates these workflows with reproducible synthetic data; real-port deployment requires operational data integration and independent validation.
