#!/usr/bin/env python3
"""
Full Event Extraction Validation Test

This script validates the complete event extraction pipeline:
1. Ingests a document with KNOWN events
2. Waits for worker to extract events
3. Validates extracted events against expected events
4. Generates a detailed validation report

Run with: python validate_event_extraction.py
"""

import json
import requests
import time
import uuid
import sys
from datetime import datetime
from typing import Dict, List, Any, Optional

# Configuration
MCP_URL = "http://localhost:3000/mcp/"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream"
}

# Test document with KNOWN expected events
TEST_DOCUMENT = """
Meeting Notes - Product Launch Planning
Date: March 15, 2024
Attendees: Alice Chen (PM), Bob Smith (Engineering), Carol Davis (Design)

DECISIONS MADE:
1. Alice decided to launch the product on April 1st, 2024.
2. The team agreed to use a freemium pricing model.

COMMITMENTS:
1. Bob committed to delivering the API integration by March 25th.
2. Carol will complete the UI mockups by March 20th.

ACTION ITEMS:
- Bob: Implement OAuth2 authentication
- Carol: Design the onboarding flow
- Alice: Prepare marketing materials

RISKS IDENTIFIED:
- Timeline is aggressive, may need to cut scope
- Third-party API has known reliability issues
"""

# Expected events for validation
EXPECTED_EVENTS = [
    {
        "category": "Decision",
        "description": "Launch date set to April 1st",
        "search_terms": ["april", "launch", "april 1"],
        "actors": ["Alice Chen"],
        "required": True
    },
    {
        "category": "Decision",
        "description": "Freemium pricing model adopted",
        "search_terms": ["freemium", "pricing"],
        "actors": ["team"],
        "required": True
    },
    {
        "category": "Commitment",
        "description": "API integration by March 25th",
        "search_terms": ["api", "march 25", "bob"],
        "actors": ["Bob Smith"],
        "required": True
    },
    {
        "category": "Commitment",
        "description": "UI mockups by March 20th",
        "search_terms": ["mockup", "ui", "march 20", "carol"],
        "actors": ["Carol Davis"],
        "required": True
    },
    {
        "category": "Commitment",
        "description": "OAuth2 implementation",
        "search_terms": ["oauth", "authentication"],
        "actors": ["Bob Smith"],
        "required": False
    },
    {
        "category": "Commitment",
        "description": "Onboarding flow design",
        "search_terms": ["onboarding"],
        "actors": ["Carol Davis"],
        "required": False
    },
    {
        "category": "Commitment",
        "description": "Marketing materials",
        "search_terms": ["marketing"],
        "actors": ["Alice Chen"],
        "required": False
    },
    {
        "category": "QualityRisk",
        "description": "Timeline risk",
        "search_terms": ["timeline", "aggressive", "scope"],
        "actors": [],
        "required": True
    },
    {
        "category": "QualityRisk",
        "description": "Third-party API reliability",
        "search_terms": ["reliability", "third-party", "api"],
        "actors": [],
        "required": False
    },
]


class MCPClient:
    """MCP client for testing"""

    def __init__(self, url: str):
        self.url = url
        self.session_id = None
        self.request_id = 0

    def _next_id(self) -> int:
        self.request_id += 1
        return self.request_id

    def _get_headers(self) -> Dict:
        headers = HEADERS.copy()
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _send_request(self, method: str, params: Dict = None) -> Dict:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._next_id(),
            "params": params or {}
        }

        try:
            resp = requests.post(self.url, headers=self._get_headers(), json=payload, timeout=60)

            if "Mcp-Session-Id" in resp.headers:
                self.session_id = resp.headers["Mcp-Session-Id"]

            if resp.status_code == 200:
                for line in resp.text.split('\n'):
                    if line.startswith('data:'):
                        return json.loads(line[5:].strip())

            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def initialize(self) -> bool:
        result = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "event-validation-test", "version": "1.0"},
            "capabilities": {}
        })

        success = "result" in result and "protocolVersion" in result.get("result", {})
        if success:
            self._send_request("notifications/initialized", {})
        return success

    def call_tool(self, name: str, arguments: Dict) -> Dict:
        result = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })
        return result

    def parse_tool_result(self, result: Dict) -> Dict:
        """Parse tool result and return the actual content as dict"""
        if "result" in result:
            content = result["result"].get("content", [{}])[0].get("text", "{}")
            try:
                return json.loads(content)
            except:
                return {"raw": content}
        return {"error": result.get("error", "Unknown error")}


class EventExtractionValidator:
    """Validates event extraction quality"""

    def __init__(self):
        self.client = MCPClient(MCP_URL)
        self.artifact_uid = None
        self.revision_id = None
        self.job_id = None
        self.extracted_events = []
        self.validation_results = {
            "timestamp": datetime.now().isoformat(),
            "document": "Product Launch Planning Meeting",
            "phases": [],
            "recall": {},
            "precision": {},
            "evidence": {},
            "overall": {}
        }

    def log(self, phase: str, status: str, message: str, details: Any = None):
        """Log validation step"""
        color = "\033[92m" if status == "PASS" else "\033[91m" if status == "FAIL" else "\033[93m"
        reset = "\033[0m"
        print(f"{color}[{status}]{reset} {phase}: {message}")
        if details:
            print(f"         {str(details)[:200]}")

        self.validation_results["phases"].append({
            "phase": phase,
            "status": status,
            "message": message,
            "details": details
        })

    def run_validation(self):
        """Run complete validation"""
        print("\n" + "=" * 70)
        print("EVENT EXTRACTION VALIDATION TEST")
        print("Testing full pipeline with known expected events")
        print("=" * 70 + "\n")

        # Phase 1: Initialize
        print("--- Phase 1: Connection ---\n")
        if not self.client.initialize():
            self.log("Initialize", "FAIL", "Failed to connect to MCP server")
            return False
        self.log("Initialize", "PASS", "Connected to MCP server")

        # Phase 2: Ingest document
        print("\n--- Phase 2: Document Ingestion ---\n")
        if not self.ingest_document():
            return False

        # Phase 3: Wait for extraction
        print("\n--- Phase 3: Wait for Extraction ---\n")
        if not self.wait_for_extraction():
            return False

        # Phase 4: Retrieve events
        print("\n--- Phase 4: Retrieve Events ---\n")
        if not self.retrieve_events():
            return False

        # Phase 5: Validate events
        print("\n--- Phase 5: Validate Extracted Events ---\n")
        self.validate_recall()
        self.validate_precision()
        self.validate_evidence()

        # Phase 6: Generate report
        print("\n--- Phase 6: Generate Report ---\n")
        self.generate_report()

        return True

    def ingest_document(self) -> bool:
        """Ingest test document"""
        result = self.client.call_tool("artifact_ingest", {
            "artifact_type": "note",
            "source_system": "event-validation-test",
            "content": TEST_DOCUMENT,
            "title": "Product Launch Planning Meeting",
            "source_id": f"validation-{uuid.uuid4().hex[:8]}",
            "participants": ["Alice Chen", "Bob Smith", "Carol Davis"],
            "ts": "2024-03-15T10:00:00Z"
        })

        parsed = self.client.parse_tool_result(result)

        if "error" in parsed:
            self.log("Ingest", "FAIL", f"Ingestion failed: {parsed['error']}")
            return False

        self.artifact_uid = parsed.get("artifact_uid")
        self.revision_id = parsed.get("revision_id")
        self.job_id = parsed.get("job_id")

        if self.artifact_uid and self.revision_id:
            self.log("Ingest", "PASS", f"Document ingested", {
                "artifact_uid": self.artifact_uid,
                "revision_id": self.revision_id,
                "job_id": self.job_id
            })
            return True
        else:
            self.log("Ingest", "FAIL", "Missing V3 fields in response", parsed)
            return False

    def wait_for_extraction(self, max_wait: int = 90, poll_interval: int = 3) -> bool:
        """Wait for extraction job to complete"""
        elapsed = 0
        last_status = None

        while elapsed < max_wait:
            result = self.client.call_tool("job_status", {
                "artifact_uid": self.artifact_uid
            })
            parsed = self.client.parse_tool_result(result)

            status = parsed.get("status", "UNKNOWN")

            if status != last_status:
                print(f"         Job status: {status} (elapsed: {elapsed}s)")
                last_status = status

            if status == "DONE":
                self.log("Extraction", "PASS", f"Completed in {elapsed}s")
                return True
            elif status == "FAILED":
                self.log("Extraction", "FAIL", f"Job failed: {parsed.get('last_error_message', 'Unknown')}")
                return False
            elif "V3_UNAVAILABLE" in str(parsed) or "NOT_FOUND" in str(parsed):
                self.log("Extraction", "FAIL", "V3/Postgres not available")
                return False

            time.sleep(poll_interval)
            elapsed += poll_interval

        self.log("Extraction", "FAIL", f"Timeout after {max_wait}s (job still {status})")
        return False

    def retrieve_events(self) -> bool:
        """Retrieve extracted events"""
        result = self.client.call_tool("event_list_for_artifact", {
            "artifact_uid": self.artifact_uid,
            "include_evidence": True
        })
        parsed = self.client.parse_tool_result(result)

        if "error" in parsed:
            self.log("Retrieve", "FAIL", f"Failed to retrieve events: {parsed['error']}")
            return False

        self.extracted_events = parsed.get("events", [])
        total = parsed.get("total", len(self.extracted_events))

        self.log("Retrieve", "PASS", f"Retrieved {total} events")

        # Print summary of extracted events
        print("\n         Extracted Events Summary:")
        for i, event in enumerate(self.extracted_events, 1):
            category = event.get("category", "?")
            narrative = event.get("narrative", "")[:80]
            print(f"         {i}. [{category}] {narrative}...")

        return True

    def validate_recall(self):
        """Check if all expected events were found"""
        print("\n         Checking Recall (did we find all expected events?)...\n")

        found_count = 0
        required_found = 0
        required_total = sum(1 for e in EXPECTED_EVENTS if e["required"])

        for expected in EXPECTED_EVENTS:
            found = False
            matched_event = None

            for extracted in self.extracted_events:
                narrative = extracted.get("narrative", "").lower()
                category = extracted.get("category", "")

                # Check if any search term matches
                for term in expected["search_terms"]:
                    if term.lower() in narrative:
                        found = True
                        matched_event = extracted
                        break

                if found:
                    break

            status = "PASS" if found else ("FAIL" if expected["required"] else "WARN")
            symbol = "✓" if found else "✗"

            print(f"         {symbol} {expected['description']}: {status}")
            if matched_event:
                print(f"           → Found: {matched_event.get('narrative', '')[:60]}...")

            if found:
                found_count += 1
                if expected["required"]:
                    required_found += 1

        recall_score = found_count / len(EXPECTED_EVENTS) * 100
        required_recall = required_found / required_total * 100

        self.validation_results["recall"] = {
            "total_expected": len(EXPECTED_EVENTS),
            "total_found": found_count,
            "recall_percentage": recall_score,
            "required_expected": required_total,
            "required_found": required_found,
            "required_recall_percentage": required_recall
        }

        print(f"\n         Recall Score: {found_count}/{len(EXPECTED_EVENTS)} ({recall_score:.1f}%)")
        print(f"         Required Events: {required_found}/{required_total} ({required_recall:.1f}%)")

        if required_recall >= 100:
            self.log("Recall", "PASS", f"All required events found ({required_found}/{required_total})")
        elif required_recall >= 80:
            self.log("Recall", "WARN", f"Most required events found ({required_found}/{required_total})")
        else:
            self.log("Recall", "FAIL", f"Missing required events ({required_found}/{required_total})")

    def validate_precision(self):
        """Check if extracted events are accurate"""
        print("\n         Checking Precision (are extracted events valid?)...\n")

        valid_count = 0
        issues = []

        for i, event in enumerate(self.extracted_events, 1):
            event_issues = []

            # Check narrative quality
            narrative = event.get("narrative", "")
            if len(narrative) < 20:
                event_issues.append("Narrative too short")
            if len(narrative) > 500:
                event_issues.append("Narrative too long")

            # Check category is valid
            valid_categories = ["Commitment", "Execution", "Decision", "Collaboration",
                               "QualityRisk", "Feedback", "Change", "Stakeholder"]
            if event.get("category") not in valid_categories:
                event_issues.append(f"Invalid category: {event.get('category')}")

            # Check confidence
            confidence = event.get("confidence", 0)
            if confidence < 0.5:
                event_issues.append(f"Low confidence: {confidence}")

            # Check actors exist in document
            actors = event.get("actors", [])
            # Parse if actors is a JSON string
            if isinstance(actors, str):
                try:
                    import json
                    actors = json.loads(actors)
                except:
                    actors = []
            for actor in actors:
                # Handle both string and dict formats
                if isinstance(actor, dict):
                    ref = actor.get("ref", "")
                else:
                    ref = str(actor)
                if ref and ref.lower() not in TEST_DOCUMENT.lower() and ref.lower() != "team":
                    event_issues.append(f"Actor '{ref}' not in document")

            if not event_issues:
                valid_count += 1
                print(f"         ✓ Event {i}: Valid")
            else:
                print(f"         ✗ Event {i}: Issues - {', '.join(event_issues)}")
                issues.extend(event_issues)

        precision_score = valid_count / len(self.extracted_events) * 100 if self.extracted_events else 0

        self.validation_results["precision"] = {
            "total_events": len(self.extracted_events),
            "valid_events": valid_count,
            "precision_percentage": precision_score,
            "issues": issues
        }

        print(f"\n         Precision Score: {valid_count}/{len(self.extracted_events)} ({precision_score:.1f}%)")

        if precision_score >= 90:
            self.log("Precision", "PASS", f"High precision ({precision_score:.1f}%)")
        elif precision_score >= 70:
            self.log("Precision", "WARN", f"Moderate precision ({precision_score:.1f}%)")
        else:
            self.log("Precision", "FAIL", f"Low precision ({precision_score:.1f}%)")

    def validate_evidence(self):
        """Check if evidence correctly links to source"""
        print("\n         Checking Evidence Quality...\n")

        total_evidence = 0
        valid_evidence = 0

        for i, event in enumerate(self.extracted_events, 1):
            evidence_list = event.get("evidence", [])
            event_valid = 0

            for ev in evidence_list:
                total_evidence += 1
                quote = ev.get("quote", "")

                # Check if quote exists in original document
                if quote and quote in TEST_DOCUMENT:
                    valid_evidence += 1
                    event_valid += 1
                elif quote:
                    # Try fuzzy match (first 20 chars)
                    if quote[:20] in TEST_DOCUMENT:
                        valid_evidence += 1
                        event_valid += 1

            if evidence_list:
                status = "✓" if event_valid == len(evidence_list) else "~"
                print(f"         {status} Event {i}: {event_valid}/{len(evidence_list)} evidence quotes valid")

        evidence_score = valid_evidence / total_evidence * 100 if total_evidence else 100

        self.validation_results["evidence"] = {
            "total_evidence": total_evidence,
            "valid_evidence": valid_evidence,
            "evidence_percentage": evidence_score
        }

        print(f"\n         Evidence Score: {valid_evidence}/{total_evidence} ({evidence_score:.1f}%)")

        if evidence_score >= 90:
            self.log("Evidence", "PASS", f"Evidence links valid ({evidence_score:.1f}%)")
        elif evidence_score >= 70:
            self.log("Evidence", "WARN", f"Some evidence issues ({evidence_score:.1f}%)")
        else:
            self.log("Evidence", "FAIL", f"Evidence quality low ({evidence_score:.1f}%)")

    def generate_report(self):
        """Generate final validation report"""
        recall = self.validation_results["recall"]
        precision = self.validation_results["precision"]
        evidence = self.validation_results["evidence"]

        # Calculate F1 score
        r = recall.get("recall_percentage", 0) / 100
        p = precision.get("precision_percentage", 0) / 100
        f1 = 2 * (p * r) / (p + r) * 100 if (p + r) > 0 else 0

        self.validation_results["overall"] = {
            "recall": recall.get("recall_percentage", 0),
            "precision": precision.get("precision_percentage", 0),
            "evidence": evidence.get("evidence_percentage", 0),
            "f1_score": f1,
            "pass": recall.get("required_recall_percentage", 0) >= 80 and p >= 0.7
        }

        # Print summary
        print("\n" + "=" * 70)
        print("VALIDATION REPORT SUMMARY")
        print("=" * 70)
        print(f"\nDocument: Product Launch Planning Meeting")
        print(f"Events Extracted: {len(self.extracted_events)}")
        print(f"\nScores:")
        print(f"  Recall:    {recall.get('recall_percentage', 0):.1f}% ({recall.get('total_found', 0)}/{recall.get('total_expected', 0)} events)")
        print(f"  Precision: {precision.get('precision_percentage', 0):.1f}% ({precision.get('valid_events', 0)}/{precision.get('total_events', 0)} valid)")
        print(f"  Evidence:  {evidence.get('evidence_percentage', 0):.1f}% ({evidence.get('valid_evidence', 0)}/{evidence.get('total_evidence', 0)} valid)")
        print(f"  F1 Score:  {f1:.1f}%")

        overall_pass = self.validation_results["overall"]["pass"]
        if overall_pass:
            print(f"\n\033[92mOVERALL: PASS\033[0m")
        else:
            print(f"\n\033[91mOVERALL: NEEDS REVIEW\033[0m")

        # Save detailed report
        report_path = "/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/tests/e2e/event_extraction_validation_report.json"
        with open(report_path, "w") as f:
            json.dump({
                **self.validation_results,
                "extracted_events": self.extracted_events
            }, f, indent=2, default=str)
        print(f"\nDetailed report saved to: {report_path}")

        print("\n" + "=" * 70)

        return overall_pass


if __name__ == "__main__":
    validator = EventExtractionValidator()
    success = validator.run_validation()
    sys.exit(0 if success else 1)
