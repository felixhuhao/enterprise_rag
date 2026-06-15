# Documentation Map

Use this page as the entry point for repository docs.

## Stable Guides

- [Architecture](guides/architecture.md) — system diagrams, ingestion, retrieval, observability, and data flow.
- [Development Guide](guides/DEVELOPMENT.md) — Docker, local development, reset commands, verification, and troubleshooting.
- [Configuration](guides/CONFIGURATION.md) — environment variables and example `.env` files.
- [Evaluation](guides/evaluation.md) — golden set design, run modes, scoring, and UI workflow.
- [Demo Guide](guides/DEMO_GUIDE.md) — screenshot checklist, demo path, and recording outline.
- [Smoke Test](guides/smoke_test.md) — manual regression checklist.

## Active Design Work

- [Auth + Entity-Level ACL (implemented)](designs/auth_login_entity_acl_design.md) — real password login, expiring sessions, per-entity `read`/`write` grants.
- [Prompt Reliability Implementation Plan](designs/prompt_reliability_implementation_plan.md)
- [Retrieval Control Model Design](designs/retrieval_control_model_design.md)
- [Query-Intent Routing Roadmap](designs/query_intent_routing_roadmap.md)
- [Design 2A: Deterministic Intent + Shadow Routing](designs/query_intent_2a_design.md)

## Audits

- [Prompt Reliability Audit](audits/prompt_reliability_audit.md)
- [Keyword Matching Pattern Audit](audits/keyword_matching_audit.md)

## Roadmaps And Product Notes

- [Storage Layer Maturity](roadmaps/storage_layer_maturity.md)
- [Project Market Evaluation](product/project_market_evaluation.md)

## Archive

Completed implementation plans and historical roadmaps live under [archive](archive/):

- [Completed plans](archive/completed/)
- [Historical roadmaps](archive/historical/)

Archive a doc when it is implemented, explicitly superseded, or kept only as historical context.
