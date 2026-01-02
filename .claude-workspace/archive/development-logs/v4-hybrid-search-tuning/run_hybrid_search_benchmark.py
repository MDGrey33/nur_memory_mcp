import json
import http.client
import time
import re
from datetime import datetime, timezone


HOST = "localhost"
PORT = 3001
MCP_PATH = "/mcp/"
MANIFEST_PATH = "temp/benchmark_manifest.json"
RESULTS_JSON_PATH = "temp/benchmark_results_latest.json"


STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "by", "with", "at", "from",
    "is", "are", "was", "were", "be", "been", "it", "this", "that", "as",
}


def anchor_tokens(q: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", (q or "").lower())
    out: list[str] = []
    for t in toks:
        if t in STOP:
            continue
        if t.isdigit() or len(t) >= 4:
            out.append(t)
    # unique in order
    seen = set()
    uniq: list[str] = []
    for t in out:
        if t not in seen:
            uniq.append(t)
            seen.add(t)
    return uniq


def overlap(anchors: list[str], text: str) -> int:
    if not anchors or not text:
        return 0
    s = text.lower()
    return sum(1 for a in anchors if a in s)


def rpc(method: str, params: dict | None = None, sid: str | None = None, rid: int = 1):
    payload = {"jsonrpc": "2.0", "method": method, "id": rid}
    if params is not None:
        payload["params"] = params
    body = json.dumps(payload)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        headers["Mcp-Session-Id"] = sid
    c = http.client.HTTPConnection(HOST, PORT, timeout=180)
    c.request("POST", MCP_PATH, body, headers=headers)
    r = c.getresponse()
    new_sid = r.getheader("Mcp-Session-Id") or sid
    data = r.read().decode("utf-8", "replace")
    c.close()
    for line in data.split("\n"):
        if line.startswith("data:"):
            return json.loads(line[5:].strip()), new_sid
    return {"http_status": r.status, "raw": data[:200]}, new_sid


def call_tool(name: str, args: dict, sid: str, rid: int):
    t0 = time.time()
    resp, sid = rpc("tools/call", {"name": name, "arguments": args}, sid, rid)
    dt_ms = int((time.time() - t0) * 1000)
    txt = resp.get("result", {}).get("content", [{}])[0].get("text")
    return (json.loads(txt) if txt else resp), sid, dt_ms


def corpus_50() -> list[dict]:
    """
    Returns a list of artifact_ingest argument dicts.
    All are small-ish except chunk-stress docs, which are moderately long.
    """
    docs: list[dict] = []

    def add(**kwargs):
        base = {
            "source_system": "manual",
            "sensitivity": "normal",
            "visibility_scope": "me",
        }
        base.update(kwargs)
        docs.append(base)

    # -------------------------
    # Connected chains (25)
    # -------------------------
    projects = [
        ("Alpha", "January 15", "security audit", "John Rivera", "Maria Diaz"),
        ("Beta", "February 5", "pen test", "Sam Patel", "Priya Shah"),
        ("Gamma", "March 12", "security audit", "Lena Kim", "Omar Hassan"),
        ("Delta", "April 20", "security audit", "Evan Brooks", "Sara Nguyen"),
        ("Epsilon", "May 3", "pen test", "Noah Chen", "Ava Singh"),
    ]

    for idx, (proj, due, audit_type, lead, pm) in enumerate(projects, start=1):
        p = proj.lower()
        shared = "Jordan Lee (Security)"
        shared_sys = "Auth Gateway"

        add(
            artifact_type="transcript",
            source_id=f"bench-v4-{p}-01-kickoff",
            title=f"{proj} kickoff transcript",
            source_type="transcript",
            document_date="2025-12-01",
            content=(
                f"{proj} Kickoff Meeting\n"
                f"Attendees: {pm} (PM), {lead} (Dev Lead), {shared}\n\n"
                f"{lead}: I commit to delivering the API by {due}.\n"
                f"{shared}: There is a risk — we're waiting on the {audit_type} results.\n"
                f"{pm}: Decision: use PostgreSQL and standardize on {shared_sys}.\n"
                f"Action: {pm} to schedule follow-up with Security.\n"
            ),
        )

        add(
            artifact_type="note",
            source_id=f"bench-v4-{p}-02-standup",
            title=f"{proj} standup",
            source_type="meeting_notes",
            document_date="2025-12-05",
            content=(
                f"{proj} Standup Notes\n"
                f"{lead}: API delivery target remains {due}.\n"
                f"{pm}: Blocker risk is still the {audit_type} timeline.\n"
                f"{shared}: Please update the threat model for {shared_sys}.\n"
            ),
        )

        add(
            artifact_type="email",
            source_id=f"bench-v4-{p}-03-audit-update",
            title=f"{proj} {audit_type} update",
            source_type="email",
            document_date="2025-12-10",
            content=(
                f"From: security@company.com\n"
                f"Subject: {proj} {audit_type} status\n\n"
                f"{audit_type.title()} results are in progress.\n"
                f"Risk: if delayed, it may impact {due}.\n"
                f"{shared} will provide an update by Friday.\n"
            ),
        )

        add(
            artifact_type="note",
            source_id=f"bench-v4-{p}-04-decision",
            title=f"{proj} decision memo",
            source_type="meeting_notes",
            document_date="2025-12-11",
            content=(
                f"{proj} Decision Memo\n"
                f"Decision: require {shared_sys} integration for all endpoints.\n"
                f"Reason: simplify audit trail and reduce auth inconsistencies.\n"
                f"Commitment: {lead} to integrate {shared_sys} by {due}.\n"
            ),
        )

        add(
            artifact_type="email",
            source_id=f"bench-v4-{p}-05-followup",
            title=f"{proj} follow-up actions",
            source_type="email",
            document_date="2025-12-12",
            content=(
                f"From: {pm.lower().replace(' ','.')}@company.com\n"
                f"Subject: {proj} follow-ups\n\n"
                f"Action: {lead} to confirm API delivery by {due}.\n"
                f"Action: {pm} to confirm {audit_type} sign-off with {shared}.\n"
                f"Risk: unconfirmed sign-off could slip the date.\n"
            ),
        )

    # -------------------------
    # Noise zoo (15)
    # -------------------------
    noise = [
        ("vendorx", "VendorX payment delays pose a risk to launch timeline."),
        ("vendory", "VendorY contract renewal is a risk for onboarding schedule."),
        ("qa", "QA team understaffed is a risk for release quality."),
        ("perf", "Performance regression risk after animation refactor."),
        ("authbug", "Login session timeout bug is a risk for user retention."),
        ("migration", "Database migration risk due to schema drift."),
        ("compliance", "SOC2 audit risk if evidence collection slips."),
        ("deps", "Dependency upgrade risk (breaking changes)."),
        ("infra", "Infra outage risk during peak traffic."),
        ("pricing", "Pricing change risk due to legal review delay."),
        ("mobile", "iOS 18 compatibility risk for mobile launch."),
        ("api", "Third-party API reliability risk impacting integrations."),
        ("budget", "Budget approval risk for additional contractor."),
        ("training", "Security training delay risk for compliance deadline."),
        ("scope", "Scope creep risk impacting milestone."),
    ]
    for i, (tag, line) in enumerate(noise, start=1):
        add(
            artifact_type="note",
            source_id=f"bench-v4-noise-{i:02d}-{tag}",
            title=f"Noise note {i:02d} ({tag})",
            source_type="document",
            document_date="2025-12-20",
            content=(
                f"Note\n"
                f"Risk: {line}\n"
                f"Decision: track in weekly status.\n"
                f"Action: owner to report by Friday.\n"
            ),
        )

    # -------------------------
    # Chunk stress (10) - moderately long
    # -------------------------
    handbook_topics = [
        "Code Quality and Testing Standards",
        "Incident Response Runbook",
        "Observability and Logging Guidelines",
        "Onboarding Guide for New Engineers",
        "API Design Standards",
        "Release Management Process",
        "Security Basics for Developers",
        "Performance Optimization Guide",
        "Reliability Patterns and SLOs",
        "Architecture Decision Records Guide",
    ]
    filler = (
        "This document covers general engineering practices: code quality, testing, documentation, "
        "linting, CI, code review, refactoring, reliability, observability, and operational hygiene.\n"
    )
    for i, title in enumerate(handbook_topics, start=1):
        add(
            artifact_type="doc",
            source_id=f"bench-v4-handbook-{i:02d}",
            title=f"Handbook: {title}",
            source_type="document",
            document_date="2025-11-01",
            content=(f"# {title}\n\n" + (filler * 35)),  # long enough to chunk, but not enormous
        )

    assert len(docs) == 50, f"Expected 50 docs, got {len(docs)}"
    return docs


def corpus_realistic_50() -> list[dict]:
    """
    Realistic, diverse ~50-doc corpus designed to:
    - include multiple document types (meeting_notes, transcript, ticket, doc, policy, contract, chat, email, wiki)
    - create deliberate cross-document links (shared people + shared systems + shared vendors)
    - avoid overfitting on a single keyword/storyline
    """
    docs: list[dict] = []

    def add(**kwargs):
        base = {
            "source_system": "manual",
            "sensitivity": "normal",
            "visibility_scope": "me",
        }
        base.update(kwargs)
        docs.append(base)

    # -------------------------
    # Connected project sets (4 projects × 8 docs = 32)
    # -------------------------
    # Shared cross-project entities:
    # - Jordan Lee (Security) appears across all projects
    # - Auth Gateway appears across all projects
    # - VendorX appears in 2 projects to create a shared vendor link
    projects = [
        ("Alpha", "January 15", "John Rivera", "Maria Diaz"),
        ("Beta", "February 5", "Sam Patel", "Priya Shah"),
        ("Gamma", "March 12", "Lena Kim", "Omar Hassan"),
        ("Delta", "April 20", "Evan Brooks", "Sara Nguyen"),
    ]
    shared_security = "Jordan Lee (Security)"
    shared_system = "Auth Gateway"

    for proj, due, lead, pm in projects:
        p = proj.lower()
        audit_type = "security audit" if proj in ("Alpha", "Gamma", "Delta") else "pen test"
        vendor = "VendorX" if proj in ("Alpha", "Beta") else "VendorY"

        # 1) Kickoff transcript
        add(
            artifact_type="transcript",
            source_type="transcript",
            source_id=f"bench-v5-{p}-01-kickoff",
            title=f"{proj} kickoff transcript",
            document_date="2025-12-01",
            content=(
                f"{proj} Kickoff Meeting\n"
                f"Attendees: {pm} (PM), {lead} (Dev Lead), {shared_security}\n\n"
                f"{lead}: I commit to delivering the API by {due}.\n"
                f"{shared_security}: There is a risk — we're waiting on the {audit_type} results.\n"
                f"{pm}: Decision: use PostgreSQL and standardize on {shared_system}.\n"
                f"Action: {pm} to schedule follow-up with Security.\n"
            ),
        )

        # 2) Project plan ticket
        add(
            artifact_type="doc",
            source_type="ticket",
            source_id=f"bench-v5-{p}-02-plan-ticket",
            title=f"{proj} project plan (ticket)",
            document_date="2025-12-02",
            content=(
                f"{proj} Project Plan\n"
                f"Milestone: API delivery by {due}\n"
                f"Owner: {lead}\n"
                f"Dependency: {audit_type} sign-off by {shared_security}\n"
                f"Risk: vendor dependency on {vendor} integration\n"
            ),
        )

        # 3) Architecture doc (explicit subjects/actors)
        add(
            artifact_type="doc",
            source_type="document",
            source_id=f"bench-v5-{p}-03-architecture",
            title=f"{proj} architecture: {shared_system} integration",
            document_date="2025-12-03",
            content=(
                f"{proj} Architecture Doc\n"
                f"Decision: standardize on {shared_system} for authn/authz.\n"
                f"Actors: {lead} (Dev Lead), {shared_security}.\n"
                f"Subject: {shared_system}.\n"
                f"Requirement: audit trail, threat model, and key rotation policy.\n"
            ),
        )

        # 4) Architecture review meeting notes
        add(
            artifact_type="note",
            source_type="meeting_notes",
            source_id=f"bench-v5-{p}-04-arch-review",
            title=f"{proj} architecture review notes",
            document_date="2025-12-04",
            content=(
                f"{proj} Architecture Review\n"
                f"{shared_security} reviewed {shared_system} approach.\n"
                f"Decision: proceed.\n"
                f"Commitment: {lead} will complete integration by {due}.\n"
                f"Risk: {audit_type} timeline may impact the milestone.\n"
            ),
        )

        # 5) Standup note
        add(
            artifact_type="note",
            source_type="meeting_notes",
            source_id=f"bench-v5-{p}-05-standup",
            title=f"{proj} standup notes",
            document_date="2025-12-05",
            content=(
                f"{proj} Standup\n"
                f"{lead}: API delivery target remains {due}.\n"
                f"{pm}: Blocker risk is {audit_type} schedule.\n"
                f"{shared_security}: Please update the threat model for {shared_system}.\n"
            ),
        )

        # 6) Security/audit update email
        add(
            artifact_type="email",
            source_type="email",
            source_id=f"bench-v5-{p}-06-audit-update",
            title=f"{proj} {audit_type} update",
            document_date="2025-12-10",
            content=(
                f"From: security@company.com\n"
                f"Subject: {proj} {audit_type} status\n\n"
                f"{audit_type.title()} results are in progress.\n"
                f"Risk: delay may impact {due}.\n"
                f"Owner: {shared_security}.\n"
            ),
        )

        # 7) Vendor integration note (shared vendor link)
        add(
            artifact_type="note",
            source_type="document",
            source_id=f"bench-v5-{p}-07-vendor-note",
            title=f"{proj} vendor integration note ({vendor})",
            document_date="2025-12-11",
            content=(
                f"{proj} Vendor Integration\n"
                f"Decision: integrate with {vendor} for payments.\n"
                f"Risk: vendor delays could affect the API delivery by {due}.\n"
                f"Action: {lead} to review {vendor} contract.\n"
            ),
        )

        # 8) Follow-up actions email
        add(
            artifact_type="email",
            source_type="email",
            source_id=f"bench-v5-{p}-08-followup",
            title=f"{proj} follow-up actions",
            document_date="2025-12-12",
            content=(
                f"From: {pm.lower().replace(' ','.')}@company.com\n"
                f"Subject: {proj} follow-ups\n\n"
                f"Action: {lead} to confirm API delivery by {due}.\n"
                f"Action: {pm} to confirm {audit_type} sign-off with {shared_security}.\n"
                f"Risk: unconfirmed sign-off could slip the date.\n"
            ),
        )

    # -------------------------
    # Distinct-but-realistic docs (18)
    # -------------------------
    # 6 chats
    for i in range(1, 7):
        add(
            artifact_type="chat",
            source_type="slack",
            source_id=f"bench-v5-chat-{i:02d}",
            title=f"slack thread {i:02d}",
            document_date="2025-12-21",
            content=(
                "#platform\n"
                f"[10:0{i}] someone: any update on the audit?\n"
                f"[10:1{i}] jordan: still waiting on results, please update threat model for Auth Gateway\n"
                f"[10:2{i}] lead: api delivery dates unchanged\n"
            ),
        )

    # 4 employee evals (distinct topic)
    for i in range(1, 5):
        add(
            artifact_type="doc",
            source_type="document",
            source_id=f"bench-v5-eval-{i:02d}",
            title=f"Performance review {i:02d}",
            document_date="2024-12-31",
            content=(
                "PERFORMANCE REVIEW\n"
                "Summary: exceeded expectations.\n"
                "Achievements: delivered milestones, improved reliability.\n"
                "Goals: lead a migration, improve documentation.\n"
            ),
        )

    # 4 policies/contracts (distinct but realistic)
    for i in range(1, 3):
        add(
            artifact_type="doc",
            source_type="contract",
            source_id=f"bench-v5-contract-{i:02d}",
            title=f"Vendor contract {i:02d}",
            document_date="2025-10-01",
            content=(
                "CONTRACT SUMMARY\n"
                "Vendor terms, SLA, renewal conditions.\n"
                "Risk: renewal delays and legal review.\n"
            ),
        )
    for i in range(3, 5):
        add(
            artifact_type="doc",
            source_type="policy",
            source_id=f"bench-v5-policy-{i:02d}",
            title=f"Engineering policy {i:02d}",
            document_date="2025-10-02",
            content=(
                "ENGINEERING POLICY\n"
                "Quality, security, and change management policy.\n"
                "Applies to all teams; includes audit requirements.\n"
            ),
        )

    # 4 handbooks (chunk stress but realistic)
    filler = (
        "This handbook covers general engineering practices: code quality, testing, documentation, "
        "linting, CI, code review, reliability, and observability.\n"
    )
    for i in range(1, 5):
        add(
            artifact_type="doc",
            source_type="wiki",
            source_id=f"bench-v5-handbook-{i:02d}",
            title=f"Engineering handbook section {i:02d}",
            document_date="2025-11-01",
            content=("# Engineering Handbook\n\n" + (filler * 30)),
        )

    assert len(docs) == 50, f"Expected 50 docs, got {len(docs)}"
    return docs

QUERIES = [
    ("Q_alpha", "security audit risk January 15 API delivery Alpha"),
    ("Q_beta", "pen test risk February 5 API delivery Beta"),
    ("Q_gamma", "security audit risk March 12 API delivery Gamma"),
    ("Q_delta", "security audit risk April 20 API delivery Delta"),
    ("Q_epsilon", "pen test risk May 3 API delivery Epsilon"),
    ("Q_jordan", "Jordan Lee security audit"),
    ("Q_auth_gateway", "Auth Gateway decision"),
    ("Q_risk", "risk"),
    ("Q_vendor_risk", "vendor risk"),
    ("Q_audit", "audit"),
    ("Q_code_quality", "code quality testing standards"),
]

def load_manifest() -> dict:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    print(f"Target MCP: http://{HOST}:{PORT}{MCP_PATH}")

    _, sid = rpc(
        "initialize",
        {"protocolVersion": "2024-11-05", "clientInfo": {"name": "bench50", "version": "1.0"}, "capabilities": {}},
        None,
        1,
    )
    if not sid:
        raise SystemExit("Failed to initialize MCP session (no session id)")

    docs = corpus_realistic_50()
    artifact_ids: list[str] = []

    print(f"Ingesting {len(docs)} docs...")
    rid = 10
    for d in docs:
        payload = {
            "artifact_type": d["artifact_type"],
            "source_system": d["source_system"],
            "source_id": d["source_id"],
            "source_type": d.get("source_type", "document"),
            "title": d["title"],
            "content": d["content"],
            "document_date": d.get("document_date"),
            "sensitivity": d.get("sensitivity", "normal"),
            "visibility_scope": d.get("visibility_scope", "me"),
        }
        res, sid, lat = call_tool("artifact_ingest", payload, sid, rid)
        rid += 1
        aid = res.get("artifact_id") if isinstance(res, dict) else None
        if not aid:
            raise SystemExit(f"artifact_ingest failed for {d['source_id']}: {res}")
        artifact_ids.append(aid)
        if len(artifact_ids) % 10 == 0:
            print(f"  ingested {len(artifact_ids)}/{len(docs)} (last latency={lat}ms)")

    print("Waiting for extraction jobs to complete (job_status)...")
    # bounded wait: up to 15 minutes total
    deadline = time.time() + (15 * 60)
    remaining = set(artifact_ids)
    while remaining and time.time() < deadline:
        done_now = set()
        for aid in list(remaining)[:20]:  # batch polling
            st, sid, _ = call_tool("job_status", {"artifact_id": aid}, sid, rid)
            rid += 1
            status = (st.get("status") if isinstance(st, dict) else None) or "UNKNOWN"
            if status in ("DONE", "FAILED"):
                done_now.add(aid)
        remaining -= done_now
        if remaining:
            print(f"  remaining: {len(remaining)}")
            time.sleep(2)

    if remaining:
        print(f"WARNING: timed out waiting for {len(remaining)} artifacts; proceeding to benchmark anyway.")

    # Benchmark runs (manifest-driven)
    manifest = load_manifest()
    tests = manifest.get("tests", [])
    defaults = manifest.get("defaults", {})
    limit = int(defaults.get("limit", 10))
    include_events = bool(defaults.get("include_events", True))
    runs = int(defaults.get("runs", 3))

    print("Running hybrid_search benchmark suite (manifest)...")
    run_ts = datetime.now(timezone.utc).isoformat()

    rows = []
    for t in tests:
        qid = t.get("id") or "unknown"
        q = t.get("query") or ""
        stratum = t.get("stratum") or "unknown"
        expected = (t.get("expected") or {})
        rc_mode = expected.get("related_context_mode", "dont_care")
        if rc_mode not in ("must_have", "must_not", "dont_care"):
            rc_mode = "dont_care"

        anchors_any = t.get("anchors_any") or []
        # For scoring, build anchors from query and also include any explicit anchor phrases.
        anchors = anchor_tokens(q)
        for a in anchors_any:
            a_low = str(a).lower()
            if a_low not in anchors:
                anchors.append(a_low)

        specific = len(anchor_tokens(q)) >= 5
        min_overlap = 2 if specific else 1

        for run in range(1, runs + 1):
            payload, sid, lat = call_tool(
                "hybrid_search",
                {"query": q, "limit": limit, "include_events": include_events},
                sid,
                rid,
            )
            rid += 1
            prim = payload.get("primary_results", []) if isinstance(payload, dict) else []
            rc = payload.get("related_context", []) if isinstance(payload, dict) else []

            evs = [r for r in prim if isinstance(r, dict) and r.get("type") == "event"]
            top_evs = evs[:3]
            off_topic = sum(1 for ev in top_evs if overlap(anchors, ev.get("narrative", "")) < min_overlap)

            chunk_noise = 0
            for r in prim:
                if isinstance(r, dict) and r.get("collection") == "artifact_chunks":
                    if overlap(anchors, r.get("content", "")) == 0:
                        chunk_noise += 1
            chunk_noise_rate = (chunk_noise / len(prim)) if prim else 0.0

            rc_off = None
            if specific:
                rc_off_count = 0
                for item in (rc or []):
                    if isinstance(item, dict) and overlap(anchors, item.get("summary", "")) < min_overlap:
                        rc_off_count += 1
                rc_off = (rc_off_count / len(rc)) if rc else 0.0

            rc_count = len(rc) if isinstance(rc, list) else 0

            rows.append(
                {
                    "test_id": qid,
                    "stratum": stratum,
                    "query": q,
                    "run": run,
                    "lat_ms": lat,
                    "off_topic_events_top3": off_topic if specific else None,
                    "chunk_noise_rate": chunk_noise_rate,
                    "related_context_count": rc_count,
                    "related_context_offtopic": rc_off,
                    "event_count": len(evs),
                    "related_context_mode": rc_mode,
                }
            )

    # Aggregate scorecard
    def mean(xs):
        xs = list(xs)
        return (sum(xs) / len(xs)) if xs else 0.0

    strata = sorted({r["stratum"] for r in rows})
    scorecard = {"run_ts_utc": run_ts, "rows": rows, "by_stratum": {}}
    for s in strata:
        s_rows = [r for r in rows if r["stratum"] == s]
        must_have = [r for r in s_rows if r["related_context_mode"] == "must_have"]
        must_not = [r for r in s_rows if r["related_context_mode"] == "must_not"]

        hit_rate = mean(1.0 for r in must_have if r["related_context_count"] >= 1) if must_have else None
        fp_rate = mean(1.0 for r in must_not if r["related_context_count"] >= 1) if must_not else None
        precision_fail = mean(1.0 for r in s_rows if (r["off_topic_events_top3"] is not None and r["off_topic_events_top3"] > 0))

        scorecard["by_stratum"][s] = {
            "n_rows": len(s_rows),
            "related_context_hit_rate": hit_rate,
            "related_context_false_positive_rate": fp_rate,
            "event_precision_fail_rate": precision_fail,
            "chunk_noise_rate_avg": mean(r["chunk_noise_rate"] for r in s_rows),
            "lat_ms_avg": mean(r["lat_ms"] for r in s_rows),
        }

    with open(RESULTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(scorecard, f, indent=2)

    # Print a markdown table to stdout (so it can be copy/pasted).
    print("\n### Benchmark Results (Manifest)")
    print(f"Run timestamp (UTC): {run_ts}")
    print("| Test | Stratum | Run | Latency (ms) | Off-topic events in top3 | Chunk noise rate | related_context count | event_count | related_context_mode |")
    print("|------|---------|-----|--------------|--------------------------|------------------|----------------------|------------|---------------------|")
    for r in rows:
        def fmt(x):
            if x is None:
                return "n/a"
            if isinstance(x, float):
                return f"{x:.2f}"
            return str(x)
        print(
            f"| {r['test_id']} | {r['stratum']} | {r['run']} | {r['lat_ms']} | {fmt(r['off_topic_events_top3'])} | "
            f"{fmt(r['chunk_noise_rate'])} | {r['related_context_count']} | {r['event_count']} | "
            f"{r['related_context_mode']} |"
        )

    # Append to benchmark markdown (human-readable history)
    out_md = "temp/hybrid_search_benchmark.md"
    with open(out_md, "a", encoding="utf-8") as f:
        f.write("\n\n")
        f.write("### Benchmark Results (Manifest)\n")
        f.write(f"Run timestamp (UTC): {run_ts}\n\n")
        f.write(f"Manifest: `{MANIFEST_PATH}`\n")
        f.write(f"Scorecard JSON: `{RESULTS_JSON_PATH}`\n\n")
        f.write("| Test | Stratum | Run | Latency (ms) | Off-topic events in top3 | Chunk noise rate | related_context count | event_count | related_context_mode |\n")
        f.write("|------|---------|-----|--------------|--------------------------|------------------|----------------------|------------|---------------------|\n")
        for r in rows:
            def fmt2(x):
                if x is None:
                    return "n/a"
                if isinstance(x, float):
                    return f"{x:.2f}"
                return str(x)
            f.write(
                f"| {r['test_id']} | {r['stratum']} | {r['run']} | {r['lat_ms']} | {fmt2(r['off_topic_events_top3'])} | "
                f"{fmt2(r['chunk_noise_rate'])} | {r['related_context_count']} | {r['event_count']} | "
                f"{r['related_context_mode']} |\n"
            )

        f.write("\n#### Stratum summary\n")
        f.write("| Stratum | related_context hit rate | related_context FP rate | event precision fail rate | avg chunk noise | avg latency (ms) |\n")
        f.write("|--------|--------------------------|-------------------------|---------------------------|----------------|------------------|\n")
        for s, v in scorecard["by_stratum"].items():
            def fnum(x):
                if x is None:
                    return "n/a"
                return f"{x:.2f}"
            f.write(
                f"| {s} | {fnum(v['related_context_hit_rate'])} | {fnum(v['related_context_false_positive_rate'])} | "
                f"{fnum(v['event_precision_fail_rate'])} | {v['chunk_noise_rate_avg']:.2f} | {v['lat_ms_avg']:.0f} |\n"
            )

    print(f"\nWrote scorecard JSON to {RESULTS_JSON_PATH}")
    print(f"Appended results to {out_md}")


if __name__ == "__main__":
    main()


