# Documentation Index

**Last Updated**: 2026-01-13
**Current Version**: V9 Consolidation
**Total Docs**: 134 markdown files

---

## Quick Navigation

| I need to... | Go to |
|--------------|-------|
| Understand the project | `CLAUDE.md`, `README.md` |
| Deploy/run the server | `deployment/QUICK-START.md` |
| See current work | `specs/v9-consolidation.md` |
| Run benchmarks | `benchmarks/README.md` |
| Find historical context | `archive/` |

---

## Document Status Legend

| Status | Meaning | Action |
|--------|---------|--------|
| **ACTIVE** | Current, authoritative | Keep updated |
| **REFERENCE** | Stable, rarely changes | Update on major changes |
| **ARCHIVE** | Historical, superseded | Never update |
| **OUTDATED** | Needs review/update | Fix or archive |

---

## Complete Document Map

### Root Level (2 files)

| File | Status | Description |
|------|--------|-------------|
| `CLAUDE.md` | **ACTIVE** | Claude Code instructions, commands, architecture overview |
| `README.md` | **ACTIVE** | Project overview, setup guide, client configuration |

---

### Specs (12 files)

#### Active Specs
| File | Status | Description |
|------|--------|-------------|
| `specs/v9-consolidation.md` | **ACTIVE** | V9 release plan, current work |
| `specs/v9-phase1-spec.md` | **ACTIVE** | Phase 1 extraction fix specification |
| `specs/v9-phase1-investigation.md` | **ACTIVE** | Investigation findings |
| `specs/v10-cognee-comparison.md` | **ACTIVE** | V10 Cognee side-by-side comparison plan |

#### Reference Specs (Completed)
| File | Status | Description |
|------|--------|-------------|
| `specs/v7-quality-benchmarks.md` | REFERENCE | Benchmark framework design |
| `specs/v7.1-outcome-quality-eval.md` | REFERENCE | Outcome evaluation design |
| `specs/v7.2-cleanup-plan.md` | REFERENCE | V7.2 cleanup (completed) |
| `specs/v7.3-category-expansion-research.md` | REFERENCE | Dynamic categories research |
| `specs/v7.3-phase1-implementation.md` | REFERENCE | V7.3 implementation (completed) |
| `specs/v8-explicit-edges.md` | REFERENCE | Edge/relationship model |
| `specs/v6.2-documentation-cleanup-plan.md` | REFERENCE | Doc cleanup (completed) |

---

### Architecture (1 file)

| File | Status | Description |
|------|--------|-------------|
| `architecture/README.md` | **ACTIVE** | Current architecture overview |

*V1 diagrams archived to `archive/architecture/v1/`*

---

### Deployment (9 files)

| File | Status | Description |
|------|--------|-------------|
| `deployment/README.md` | **ACTIVE** | Deployment overview |
| `deployment/QUICK-START.md` | **ACTIVE** | 30-second setup |
| `deployment/CHEATSHEET.md` | **ACTIVE** | Commands quick reference |
| `deployment/ENVIRONMENTS.md` | **ACTIVE** | Port configs, troubleshooting |
| `deployment/v9-phase1-notes.md` | **ACTIVE** | V9 deployment notes |
| `deployment/deployment-guide.md` | REFERENCE | Full deployment guide |
| `deployment/monitoring/README.md` | REFERENCE | Monitoring setup |
| `deployment/DEPLOYMENT-SUMMARY.md` | ARCHIVE | V1 deployment summary |
| `deployment/INDEX.md` | ARCHIVE | V1 deployment index |

*V3 deployment docs archived to `archive/deployment/v3/`*

---

### Benchmarks (5 files)

| File | Status | Description |
|------|--------|-------------|
| `benchmarks/README.md` | **ACTIVE** | Benchmark overview |
| `benchmarks/OUTCOME_EVAL_PLAN.md` | REFERENCE | Outcome test documentation |
| `benchmarks/external_datasets/msmarco/README.md` | REFERENCE | MS MARCO evaluation |
| `benchmarks/archive/V7_BENCHMARK_DEBUG_REPORT.md` | ARCHIVE | Debug report |
| `benchmarks/archive/V7.1_ALTERNATIVE_EVAL_PROPOSAL.md` | ARCHIVE | Alternative eval proposal |

---

### Implementation (4 files)

| File | Status | Description |
|------|--------|-------------|
| `implementation/mcp-server/README.md` | **ACTIVE** | Server setup guide |
| `implementation/IMPLEMENTATION_SUMMARY.md` | REFERENCE | Implementation overview |
| `implementation/mcp-server/tests/README.md` | REFERENCE | Test suite overview |
| `implementation/IMPLEMENTATION_CHECKLIST.md` | ARCHIVE | V1 checklist |

*V1 implementation docs archived to `archive/implementation/v1/`*

---

### Security (2 files)

| File | Status | Description |
|------|--------|-------------|
| `security/v9-phase1-audit.md` | **ACTIVE** | Latest security audit |
| `security/v5-security-audit.md` | REFERENCE | V5 audit |

*V1 security docs archived to `archive/security/v1/`, V3 to `archive/security/v3/`*

---

### Tests (3 files)

| File | Status | Description |
|------|--------|-------------|
| `tests/v6/README.md` | **ACTIVE** | Test organization |
| `tests/TEST_SUMMARY.md` | REFERENCE | Test coverage summary |
| `tests/TESTING_PROGRESS.md` | REFERENCE | Testing progress tracker |

---

### Claude Config (17 files)

#### Commands (5 files)
| File | Description |
|------|-------------|
| `.claude/commands/build.md` | /build command |
| `.claude/commands/status.md` | /status command |
| `.claude/commands/approve.md` | /approve command |
| `.claude/commands/feedback.md` | /feedback command |
| `.claude/commands/ui-test.md` | /ui-test command |

#### Docs (5 files)
| File | Description |
|------|-------------|
| `.claude/docs/claude-mind.md` | Workflow overview |
| `.claude/docs/workflow.md` | 10-phase development cycle |
| `.claude/docs/quality-gates.md` | Quality gate definitions |
| `.claude/docs/learning-system.md` | Learning system |
| `.claude/docs/testing-requirements.md` | Testing requirements |

#### Skills (8 files)
| File | Description |
|------|-------------|
| `.claude/skills/frontend/SKILL.md` | Frontend skill |
| `.claude/skills/backend/SKILL.md` | Backend skill |
| `.claude/skills/api-design/SKILL.md` | API design skill |
| `.claude/skills/architecture/SKILL.md` | Architecture skill |
| `.claude/skills/deployment/SKILL.md` | Deployment skill |
| `.claude/skills/code-review/SKILL.md` | Code review skill |
| `.claude/skills/security-audit/SKILL.md` | Security audit skill |
| `.claude/skills/test-automation/SKILL.md` | Test automation skill |

---

### Archive (78 files)

All files in `archive/` are historical and should NOT be updated.

#### V1 (Dec 2025) - 15 files
| File | Description |
|------|-------------|
| `archive/chroma_mcp_memory_v1.md` | Original build notes |
| `archive/specs/v1-specification.md` | V1 spec |
| `archive/architecture/ADR-001-docker-first.md` | Docker-first decision |
| `archive/architecture/ADR-002-chromadb-vector-store.md` | ChromaDB decision |
| `archive/architecture/ADR-003-separation-of-concerns.md` | Layer separation |
| `archive/architecture/ADR-004-two-collection-model.md` | History/memory model |
| `archive/architecture/v1-README.md` | V1 architecture overview |
| `archive/architecture/v1/component-diagram.md` | V1 component diagram |
| `archive/architecture/v1/data-flows.md` | V1 data flows |
| `archive/architecture/v1/directory-structure.md` | V1 directory structure |
| `archive/implementation/v1/ARCHITECTURE_DIAGRAM.md` | V1 architecture diagram |
| `archive/implementation/v1/QUICKSTART.md` | V1 quickstart |
| `archive/implementation/v1/MCP-INTEGRATION.md` | V1 MCP integration |
| `archive/security/v1/README.md` | V1 security overview |
| `archive/security/v1/threat-model.md` | V1 threat model |
| `archive/security/v1/security-recommendations.md` | V1 recommendations |

#### V2 (Dec 2025) - 13 files
| File | Description |
|------|-------------|
| `archive/requirments.md` | V2 requirements |
| `archive/specs/v2-technical-spec.md` | V2 spec |
| `archive/docs/V2_CHANGES.md` | V1→V2 changes |
| `archive/docs/ARCHITECTURE.md` | V2 architecture |
| `archive/architecture/ADR-001-embedding-strategy.md` | Embedding strategy |
| `archive/architecture/ADR-002-chunking-architecture.md` | Chunking design |
| `archive/architecture/ADR-003-hybrid-retrieval.md` | Hybrid search |
| `archive/architecture/ADR-004-module-structure.md` | Module structure |
| `archive/architecture/v2-ADR-INDEX.md` | ADR index |
| `archive/deliverables/quality-review.md` | V1 quality review |
| `archive/deliverables/v2-quality-review.md` | V2 quality review |
| `archive/security/security-audit-report.md` | V2 security audit |
| `archive/TEST_COVERAGE.md` | V2 test coverage |

#### V3 (Dec 2025) - 17 files
| File | Description |
|------|-------------|
| `archive/v3.md` | V3 brief |
| `archive/specs/v3-specification.md` | V3 spec |
| `archive/architecture/v3-architecture.md` | V3 architecture |
| `archive/architecture/adr-001-postgres-over-kafka.md` | Postgres over Kafka |
| `archive/architecture/adr-002-event-extraction-model.md` | Event extraction |
| `archive/architecture/api-design.md` | V3 API design |
| `archive/architecture/database-design.md` | V3 database design |
| `archive/deployment/README-V3.md` | V3 deployment readme |
| `archive/deployment/V3-DEPLOYMENT-SUMMARY.md` | V3 deployment summary |
| `archive/deployment/V3-INDEX.md` | V3 deployment index |
| `archive/deployment/V3-README.md` | V3 deployment readme |
| `archive/deployment/v3/deploy.md` | V3 deployment guide |
| `archive/deployment/v3/monitoring.md` | V3 monitoring guide |
| `archive/security/V3-AUDIT-SUMMARY.md` | V3 audit summary |
| `archive/security/v3-security-audit.md` | V3 security audit |
| `archive/security/v3-security-recommendations.md` | V3 recommendations |
| `archive/security/v3/dependency-audit.md` | V3 dependency audit |
| `archive/V3_IMPLEMENTATION_SUMMARY.md` | V3 implementation |

#### V4 (Dec 2025) - 19 files
| File | Description |
|------|-------------|
| `archive/v4.md` | V4 brief |
| `archive/specs/v4-specification.md` | V4 spec |
| `archive/architecture/v4/architecture-overview.md` | V4 architecture |
| `archive/architecture/v4/adr/ADR-001-entity-resolution-strategy.md` | Entity resolution |
| `archive/architecture/v4/adr/ADR-002-graph-database-choice.md` | Graph DB choice |
| `archive/architecture/v4/adr/ADR-003-entity-resolution-timing.md` | Resolution timing |
| `archive/architecture/v4/adr/ADR-004-graph-model-simplification.md` | Graph simplification |
| `archive/architecture/v4/adr/ADR-005-testing-infrastructure.md` | Testing infra |
| `archive/architecture/v4/diagrams/component-diagram.md` | V4 components |
| `archive/architecture/v4/diagrams/data-flow-diagrams.md` | V4 data flows |
| `archive/architecture/v4/diagrams/database-architecture.md` | V4 database |
| `archive/architecture/v4/diagrams/error-handling-resilience.md` | V4 error handling |
| `archive/architecture/v4/diagrams/service-interfaces.md` | V4 interfaces |
| `archive/deployment/v4/DEPLOYMENT-CHECKLIST.md` | V4 checklist |
| `archive/deployment/v4/deployment-guide.md` | V4 deployment |
| `archive/deployment/v4/monitoring.md` | V4 monitoring |
| `archive/deliverables/v4-quality-review.md` | V4 quality review |
| `archive/security/v4-security-audit.md` | V4 security audit |
| `archive/security/remediation-plan.md` | V4 remediation |
| `archive/COVERAGE-REPORT.md` | V4 coverage |
| `archive/IMPLEMENTATION-NOTES.md` | V4 notes |

#### V4 Development Logs - 4 files
| File | Description |
|------|-------------|
| `archive/development-logs/v4-hybrid-search-tuning/README.md` | Tuning overview |
| `archive/development-logs/v4-hybrid-search-tuning/debugging_progress.md` | Debug progress |
| `archive/development-logs/v4-hybrid-search-tuning/progress_plan.md` | Progress plan |
| `archive/development-logs/v4-hybrid-search-tuning/quality_measurement_plan.md` | Quality plan |

#### V5 (Dec 2025) - 13 files
| File | Description |
|------|-------------|
| `archive/specs/v5-specification.md` | V5 spec |
| `archive/specs/v5-validation.md` | V5 validation |
| `archive/specs/v5-phases/README.md` | Phases overview |
| `archive/specs/v5-phases/V5-COMPLETION-PLAN.md` | Completion plan |
| `archive/specs/v5-phases/phase-1-implementation.md` | Phase 1 |
| `archive/specs/v5-phases/phase-1a-remember.md` | remember() |
| `archive/specs/v5-phases/phase-1b-recall.md` | recall() |
| `archive/specs/v5-phases/phase-1c-forget.md` | forget() |
| `archive/specs/v5-phases/phase-1d-status.md` | status() |
| `archive/specs/v5-phases/phase-2-cleanup.md` | Phase 2 |
| `archive/specs/v5-phases/phase-2a-migration.md` | Migration |
| `archive/specs/v5-phases/phase-2b-collections.md` | Collections |
| `archive/specs/v5-phases/phase-3-deprecation.md` | Deprecation |
| `archive/specs/v5-phases/phase-4-cleanup.md` | Cleanup |
| `archive/architecture/v5/ADR-001-simplified-interface.md` | Simplified API |

#### V6 (Jan 2026) - 3 files
| File | Description |
|------|-------------|
| `archive/specs/v6-cleanup-plan.md` | V6 cleanup |
| `archive/specs/v6.1-cleanup-plan.md` | V6.1 cleanup |
| `archive/specs/v6.2-documentation-cleanup-plan.md` | V6.2 doc cleanup |

#### Other Archive - 2 files
| File | Description |
|------|-------------|
| `archive/specs/tool-consolidation-proposal.md` | Tool consolidation |
| `CODE_REVIEW_V3.md` | V3 code review |

---

### Misc (1 file)

| File | Status | Description |
|------|--------|-------------|
| `DOCS.md` | **ACTIVE** | This file |

---

## Maintenance Checklist

When making changes:

1. **After benchmark runs** → Update scores in `CLAUDE.md` and `specs/v9-consolidation.md`
2. **After code changes** → Update `CLAUDE.md` if commands/architecture changed
3. **After completing a spec** → Move to Reference section
4. **After major version** → Archive old specs

---

## Quick Commands

```bash
# Count all docs
git ls-files "*.md" | grep -v ".venv" | wc -l

# Find recently modified
git diff --name-only HEAD~5 -- "*.md"

# Find docs mentioning a version
grep -r "V9" --include="*.md" .claude-workspace/specs/

# List all archive docs
git ls-files "*.md" | grep "archive/"
```

---

## Version History

| Date | Change |
|------|--------|
| 2026-01-13 | Archived 12 outdated docs (V1/V3 era), updated versions to V9 |
| 2026-01-13 | Created documentation index with full map |
