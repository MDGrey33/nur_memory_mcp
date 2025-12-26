# Threat Model - Chroma MCP Memory V1

**Project:** MCP Memory Server
**Version:** V1 (Chroma-based implementation)
**Date:** 2025-12-25
**Methodology:** STRIDE (Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege)

---

## System Overview

### Architecture Components

```
┌─────────────────────────────────────────────────────────────┐
│                        Docker Host                           │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              mcp-memory-network (bridge)              │  │
│  │                                                        │  │
│  │   ┌──────────────┐      ┌──────────────┐             │  │
│  │   │  agent-app   │─────>│    chroma    │             │  │
│  │   │   (Python)   │ HTTP │  (ChromaDB)  │             │  │
│  │   └──────────────┘ 8000 └──────────────┘             │  │
│  │                               │                        │  │
│  │                               │                        │  │
│  │                               v                        │  │
│  │                        ┌──────────────┐                │  │
│  │                        │ chroma_data  │                │  │
│  │                        │   (volume)   │                │  │
│  │                        └──────────────┘                │  │
│  │                                                        │  │
│  │   ┌──────────────┐                                    │  │
│  │   │  chroma-mcp  │                                    │  │
│  │   │ (MCP Gateway)│                                    │  │
│  │   └──────────────┘                                    │  │
│  │                                                        │  │
│  └──────────────────────────────────────────────────────┘  │
│                          │                                  │
│                    Port 8000 (exposed)                      │
│                          │                                  │
└──────────────────────────┼──────────────────────────────────┘
                           │
                           v
                    External Access
```

### Data Flow

1. **History Append Flow**
   - Agent-app receives conversation turn
   - Validates input (HistoryTurn model)
   - Sends HTTP POST to ChromaDB /collections/history/add
   - ChromaDB stores document with embedding
   - Returns document ID

2. **Memory Write Flow**
   - Agent-app generates memory from conversation
   - Policy checks (confidence threshold, rate limit)
   - Validates input (MemoryItem model)
   - Sends HTTP POST to ChromaDB /collections/memory/add
   - ChromaDB stores memory with embedding
   - Returns document ID

3. **Context Build Flow**
   - Agent-app receives user message
   - Parallel fetch: history tail + memory recall
   - HTTP POST to ChromaDB /collections/history/get (filtered by conversation_id)
   - HTTP POST to ChromaDB /collections/memory/query (semantic search)
   - Assembles context package
   - Formats for LLM prompt

4. **Bootstrap Flow**
   - Agent-app starts
   - Checks for collections existence
   - Creates "history" and "memory" collections if missing
   - Initializes components

---

## Trust Boundaries

### TB1: Docker Network Boundary
- **Inside:** agent-app, chroma, chroma-mcp containers
- **Outside:** Host system, other Docker networks
- **Trust Level:** Containers trust each other (NO authentication)
- **Risk:** Compromised container can access all services

### TB2: Container-Host Boundary
- **Inside:** Container processes, volumes
- **Outside:** Host filesystem, host network
- **Trust Level:** Containers have limited host access via Docker
- **Risk:** Container escape, volume access from host

### TB3: Application-Database Boundary
- **Inside:** ChromaDB data storage
- **Outside:** Agent-app business logic
- **Trust Level:** Agent-app trusts ChromaDB responses
- **Risk:** Malicious queries, data corruption

### TB4: External Network Boundary
- **Inside:** Docker host
- **Outside:** External networks
- **Trust Level:** Exposed port 8000 accessible without auth
- **Risk:** Unauthorized external access

---

## Asset Inventory

### Critical Assets

| Asset | Description | Confidentiality | Integrity | Availability | Storage Location |
|-------|-------------|-----------------|-----------|--------------|------------------|
| Conversation History | Full message history | HIGH | MEDIUM | MEDIUM | ChromaDB volume |
| Long-term Memories | Extracted knowledge | HIGH | HIGH | MEDIUM | ChromaDB volume |
| User Preferences | User settings and preferences | MEDIUM | MEDIUM | LOW | ChromaDB metadata |
| Configuration Secrets | API keys, credentials (future) | CRITICAL | CRITICAL | HIGH | Environment vars |
| Application Code | Python source code | LOW | HIGH | MEDIUM | Container image |
| Embeddings | Vector representations | MEDIUM | LOW | MEDIUM | ChromaDB volume |

### Secondary Assets

| Asset | Description | Risk Level |
|-------|-------------|------------|
| Log Files | Operational and security logs | MEDIUM |
| Docker Images | Container images | MEDIUM |
| Network Traffic | Inter-service communication | HIGH |
| System Metadata | Collection names, counts | LOW |

---

## Threat Actor Analysis

### Actor 1: Malicious External Attacker
**Profile:**
- Access: Network access to exposed port 8000
- Skills: Medium to High technical capability
- Motivation: Data theft, system disruption, reconnaissance
- Resources: Automated tools, scripts, botnets

**Capabilities:**
- Port scanning and service enumeration
- HTTP request manipulation
- NoSQL injection attempts
- Denial of service attacks
- Network sniffing (if on same network)

**Attack Vectors:**
- Exposed ChromaDB port (8000)
- HTTP API endpoints
- Network traffic interception
- Resource exhaustion

---

### Actor 2: Compromised Container
**Profile:**
- Access: Inside Docker network, full container privileges
- Skills: Depends on initial compromise method
- Motivation: Lateral movement, data exfiltration, persistence
- Resources: Container capabilities, network access

**Capabilities:**
- Access to all containers on Docker network
- Direct ChromaDB API access
- Network traffic inspection
- Volume mounting (if escaped)
- Host access (if container escape successful)

**Attack Vectors:**
- Vulnerable dependencies in container
- Misconfigured Docker permissions
- Container escape vulnerabilities
- Unrestricted network access

---

### Actor 3: Malicious Insider (Application Code)
**Profile:**
- Access: Application code injection or modification
- Skills: High (understands codebase)
- Motivation: Data theft, backdoor insertion, sabotage
- Resources: Code-level access, CI/CD pipeline

**Capabilities:**
- Bypass validation logic
- Exfiltrate data via application logic
- Modify security controls
- Insert backdoors

**Attack Vectors:**
- Supply chain attacks (compromised dependencies)
- Malicious code in pull requests
- Compromised CI/CD pipeline
- Insider threat

---

### Actor 4: Host System Attacker
**Profile:**
- Access: Host filesystem and Docker daemon
- Skills: High technical capability
- Motivation: Full system compromise
- Resources: Root access, physical access, cloud admin

**Capabilities:**
- Direct volume access
- Container inspection and manipulation
- Network traffic capture
- System-level modifications

**Attack Vectors:**
- Host OS vulnerabilities
- Docker daemon exploitation
- Physical access to host
- Cloud provider compromise

---

## STRIDE Analysis

### Component: agent-app (Python Application)

#### Spoofing
**Threat:** Attacker impersonates agent-app to ChromaDB
- **Severity:** HIGH
- **Likelihood:** MEDIUM
- **Description:** No authentication between agent-app and ChromaDB. Any container on the network can impersonate agent-app.
- **Impact:** Unauthorized data access, data modification, data deletion
- **Mitigations:**
  - [ ] Implement API key authentication
  - [ ] Use mutual TLS (mTLS)
  - [ ] Network segmentation
  - [ ] Service mesh with identity

**Threat:** Attacker spoofs conversation_id to access other conversations
- **Severity:** MEDIUM
- **Likelihood:** HIGH
- **Description:** If attacker knows or guesses conversation_id, they can access history and memories.
- **Impact:** Cross-conversation data leakage
- **Mitigations:**
  - [x] Use UUIDs for conversation_id (unpredictable)
  - [ ] Implement access control checks
  - [ ] Add conversation ownership metadata

---

#### Tampering
**Threat:** Attacker modifies data in ChromaDB directly
- **Severity:** HIGH
- **Likelihood:** MEDIUM
- **Description:** Direct access to ChromaDB port allows modification of history and memories.
- **Impact:** Data corruption, false memories, conversation manipulation
- **Mitigations:**
  - [ ] Remove port exposure
  - [ ] Implement authentication
  - [ ] Add data integrity checks (checksums, signatures)
  - [ ] Audit logging

**Threat:** Man-in-the-middle attack on HTTP traffic
- **Severity:** HIGH
- **Likelihood:** MEDIUM
- **Description:** HTTP traffic between agent-app and ChromaDB is unencrypted.
- **Impact:** Data modification in transit, injection attacks
- **Mitigations:**
  - [ ] Enable TLS for all communication
  - [ ] Certificate pinning
  - [ ] Network encryption

**Threat:** Attacker modifies application code or dependencies
- **Severity:** CRITICAL
- **Likelihood:** LOW
- **Description:** Compromised Docker image or supply chain attack.
- **Impact:** Complete system compromise, backdoors, data exfiltration
- **Mitigations:**
  - [ ] Image signature verification
  - [ ] Dependency scanning
  - [ ] Read-only root filesystem
  - [ ] Supply chain security

---

#### Repudiation
**Threat:** Actions cannot be traced to specific users or services
- **Severity:** MEDIUM
- **Likelihood:** HIGH
- **Description:** No audit logging of who performed which operation.
- **Impact:** Cannot investigate security incidents, compliance violations
- **Mitigations:**
  - [ ] Implement comprehensive audit logging
  - [ ] Add correlation IDs to requests
  - [ ] Log service identity with each operation
  - [ ] Immutable audit logs

**Threat:** Log tampering after incident
- **Severity:** MEDIUM
- **Likelihood:** MEDIUM
- **Description:** Logs stored locally can be modified or deleted.
- **Impact:** Loss of forensic evidence
- **Mitigations:**
  - [ ] Send logs to external SIEM
  - [ ] Immutable log storage
  - [ ] Log file integrity monitoring

---

#### Information Disclosure
**Threat:** Network sniffing reveals conversation content
- **Severity:** HIGH
- **Likelihood:** HIGH
- **Description:** HTTP traffic contains plaintext messages and memories.
- **Impact:** Confidential data exposure, privacy violations
- **Mitigations:**
  - [ ] Enable TLS/HTTPS
  - [ ] Network encryption
  - [ ] VPN for inter-service communication

**Threat:** Exposed ChromaDB port allows data extraction
- **Severity:** HIGH
- **Likelihood:** HIGH
- **Description:** Port 8000 exposed to host allows direct database queries.
- **Impact:** Complete data exfiltration
- **Mitigations:**
  - [x] Document risk for V1
  - [ ] Remove port exposure
  - [ ] Bind to localhost only
  - [ ] Add firewall rules

**Threat:** Sensitive data in log files
- **Severity:** MEDIUM
- **Likelihood:** HIGH
- **Description:** Full message content logged at DEBUG/INFO levels.
- **Impact:** Data leakage via logs, compliance violations
- **Mitigations:**
  - [ ] Sanitize log outputs
  - [ ] Use WARN/ERROR only in production
  - [ ] Implement log scrubbing
  - [ ] Secure log storage

**Threat:** Error messages reveal internal details
- **Severity:** LOW
- **Likelihood:** MEDIUM
- **Description:** Stack traces and detailed errors expose architecture.
- **Impact:** Reconnaissance for attacks
- **Mitigations:**
  - [ ] Generic error messages to clients
  - [ ] Detailed errors only in internal logs
  - [ ] Error code system

**Threat:** Docker volume accessible from host
- **Severity:** MEDIUM
- **Likelihood:** MEDIUM
- **Description:** ChromaDB data stored unencrypted in Docker volume.
- **Impact:** Data theft via host filesystem access
- **Mitigations:**
  - [ ] Encrypted volumes
  - [ ] Host filesystem access controls
  - [ ] Volume encryption at rest

---

#### Denial of Service
**Threat:** Resource exhaustion via unlimited requests
- **Severity:** HIGH
- **Likelihood:** HIGH
- **Description:** No rate limiting on history appends or memory queries.
- **Impact:** Service unavailability, cost escalation
- **Mitigations:**
  - [ ] Implement comprehensive rate limiting
  - [ ] Request size limits
  - [ ] Connection limits
  - [ ] Resource quotas in Docker

**Threat:** Large payload attack
- **Severity:** MEDIUM
- **Likelihood:** MEDIUM
- **Description:** Validation limits exist but HTTP layer accepts unlimited sizes.
- **Impact:** Memory exhaustion, service crash
- **Mitigations:**
  - [ ] HTTP client request size limits
  - [ ] Request timeouts
  - [ ] Streaming request handling
  - [x] Application-level validation (100KB history, 2KB memory)

**Threat:** Complex query attack
- **Severity:** MEDIUM
- **Likelihood:** MEDIUM
- **Description:** Expensive semantic searches or large top-K values.
- **Impact:** CPU/memory exhaustion, slow responses
- **Mitigations:**
  - [x] Limit top-K parameter (max 8)
  - [ ] Query complexity limits
  - [ ] Query timeouts
  - [ ] Resource monitoring

**Threat:** Storage exhaustion
- **Severity:** MEDIUM
- **Likelihood:** LOW
- **Description:** Unlimited history and memory storage.
- **Impact:** Disk full, service failure
- **Mitigations:**
  - [ ] Storage quotas per conversation
  - [ ] Data retention policies
  - [ ] Disk space monitoring
  - [ ] Automatic cleanup

---

#### Elevation of Privilege
**Threat:** Container escape to host system
- **Severity:** CRITICAL
- **Likelihood:** LOW
- **Description:** Containers run as root with all capabilities.
- **Impact:** Full host compromise
- **Mitigations:**
  - [ ] Run containers as non-root user
  - [ ] Drop unnecessary capabilities
  - [ ] Use security profiles (AppArmor/SELinux)
  - [ ] Read-only root filesystem

**Threat:** Cross-container access
- **Severity:** HIGH
- **Likelihood:** MEDIUM
- **Description:** All containers on same network without isolation.
- **Impact:** Lateral movement, privilege escalation
- **Mitigations:**
  - [ ] Network segmentation
  - [ ] Service-to-service authentication
  - [ ] Network policies
  - [ ] Internal network flag

**Threat:** SQL/NoSQL injection escalates to code execution
- **Severity:** HIGH
- **Likelihood:** LOW
- **Description:** Malicious queries exploit ChromaDB vulnerabilities.
- **Impact:** Remote code execution in ChromaDB container
- **Mitigations:**
  - [x] Input validation (partial)
  - [ ] Metadata filter allowlist
  - [ ] Query complexity limits
  - [ ] ChromaDB version monitoring

**Threat:** Dependency vulnerability exploitation
- **Severity:** HIGH
- **Likelihood:** MEDIUM
- **Description:** Vulnerable packages allow arbitrary code execution.
- **Impact:** Container compromise, data access
- **Mitigations:**
  - [ ] Pin dependency versions
  - [ ] Automated vulnerability scanning
  - [ ] Regular security updates
  - [ ] Minimal dependency footprint

---

### Component: ChromaDB (Vector Database)

#### Spoofing
**Threat:** Unauthorized client impersonates legitimate service
- **Severity:** HIGH
- **Likelihood:** MEDIUM
- **Description:** No authentication on ChromaDB API.
- **Impact:** Unauthorized data access and modification
- **Mitigations:** (Same as agent-app spoofing)

---

#### Tampering
**Threat:** Direct data modification via exposed port
- **Severity:** HIGH
- **Likelihood:** HIGH
- **Description:** Port 8000 allows direct database access.
- **Impact:** Data corruption, malicious memories
- **Mitigations:** (Same as agent-app tampering)

**Threat:** Vector embedding poisoning
- **Severity:** MEDIUM
- **Likelihood:** LOW
- **Description:** Crafted inputs create misleading embeddings.
- **Impact:** Poor search results, false memory recall
- **Mitigations:**
  - [x] Input validation
  - [ ] Embedding verification
  - [ ] Anomaly detection on embeddings

---

#### Repudiation
**Threat:** No audit trail of database operations
- **Severity:** MEDIUM
- **Likelihood:** HIGH
- **Description:** ChromaDB doesn't log who performed operations.
- **Impact:** Cannot trace unauthorized access
- **Mitigations:** (Same as agent-app repudiation)

---

#### Information Disclosure
**Threat:** Data extraction via exposed API
- **Severity:** HIGH
- **Likelihood:** HIGH
- **Description:** Anyone with network access can query database.
- **Impact:** Complete data exfiltration
- **Mitigations:** (Same as agent-app information disclosure)

**Threat:** Embedding vectors reveal sensitive information
- **Severity:** MEDIUM
- **Likelihood:** LOW
- **Description:** Vector embeddings can be reverse-engineered to approximate text.
- **Impact:** Partial data recovery from embeddings
- **Mitigations:**
  - [ ] Encrypted embeddings (advanced)
  - [ ] Access control on embeddings
  - [ ] Vector space obfuscation (research)

---

#### Denial of Service
**Threat:** Database resource exhaustion
- **Severity:** HIGH
- **Likelihood:** MEDIUM
- **Description:** Complex queries or bulk operations overwhelm ChromaDB.
- **Impact:** Service unavailability
- **Mitigations:**
  - [ ] Query timeouts
  - [ ] Rate limiting at database level
  - [x] Resource limits in Docker
  - [ ] Query complexity limits

---

#### Elevation of Privilege
**Threat:** ChromaDB vulnerability exploitation
- **Severity:** HIGH
- **Likelihood:** LOW
- **Description:** Security vulnerabilities in ChromaDB allow privilege escalation.
- **Impact:** Container escape, host access
- **Mitigations:**
  - [ ] Keep ChromaDB updated
  - [ ] Security vulnerability monitoring
  - [ ] Container hardening
  - [ ] Network isolation

---

### Component: Docker Network (mcp-memory-network)

#### Spoofing
**Threat:** ARP spoofing within Docker network
- **Severity:** MEDIUM
- **Likelihood:** LOW
- **Description:** Compromised container performs ARP spoofing to intercept traffic.
- **Impact:** Man-in-the-middle attacks
- **Mitigations:**
  - [ ] Use overlay network with encryption
  - [ ] Network monitoring
  - [ ] Container isolation

---

#### Tampering
**Threat:** Man-in-the-middle on Docker bridge network
- **Severity:** HIGH
- **Likelihood:** MEDIUM
- **Description:** Compromised container intercepts and modifies traffic.
- **Impact:** Data tampering, credential theft
- **Mitigations:**
  - [ ] Enable network encryption
  - [ ] Use TLS for all communication
  - [ ] Mutual TLS authentication

---

#### Information Disclosure
**Threat:** Network traffic sniffing
- **Severity:** HIGH
- **Likelihood:** MEDIUM
- **Description:** Compromised container captures network packets.
- **Impact:** Credential theft, data exfiltration
- **Mitigations:**
  - [ ] Docker network encryption
  - [ ] TLS for all HTTP traffic
  - [ ] Network segmentation

---

#### Denial of Service
**Threat:** Network flooding
- **Severity:** MEDIUM
- **Likelihood:** LOW
- **Description:** Malicious container floods network with traffic.
- **Impact:** Network congestion, service degradation
- **Mitigations:**
  - [ ] Network rate limiting
  - [ ] Container resource limits
  - [ ] Network monitoring

---

### Component: Docker Volumes (chroma_data)

#### Tampering
**Threat:** Direct volume modification from host
- **Severity:** HIGH
- **Likelihood:** LOW
- **Description:** Attacker with host access modifies volume data.
- **Impact:** Data corruption, backdoor insertion
- **Mitigations:**
  - [ ] Host filesystem access controls
  - [ ] Volume encryption
  - [ ] File integrity monitoring

---

#### Information Disclosure
**Threat:** Volume data extraction from host
- **Severity:** HIGH
- **Likelihood:** MEDIUM
- **Description:** Attacker with host access reads volume data.
- **Impact:** Complete data breach
- **Mitigations:**
  - [ ] Volume encryption at rest
  - [ ] Host access controls
  - [ ] Filesystem permissions

**Threat:** Backup/snapshot leakage
- **Severity:** MEDIUM
- **Likelihood:** LOW
- **Description:** Volume backups stored insecurely.
- **Impact:** Data exposure via backups
- **Mitigations:**
  - [ ] Encrypted backups
  - [ ] Secure backup storage
  - [ ] Backup access controls

---

#### Denial of Service
**Threat:** Volume deletion or corruption
- **Severity:** HIGH
- **Likelihood:** LOW
- **Description:** Attacker deletes or corrupts volume.
- **Impact:** Permanent data loss
- **Mitigations:**
  - [ ] Regular backups
  - [ ] Volume snapshots
  - [ ] Access controls
  - [ ] Disaster recovery plan

---

## Attack Scenarios

### Scenario 1: External Attacker - Data Exfiltration
**Attack Path:**
1. Attacker scans host and discovers exposed port 8000
2. Identifies ChromaDB service via banner/response
3. Enumerates collections: /api/v1/collections
4. Queries memory collection: /api/v1/collections/memory/query
5. Retrieves all memories with broad query
6. Queries history collection similarly
7. Exfiltrates complete conversation history and memories

**Likelihood:** HIGH
**Impact:** CRITICAL
**Risk:** CRITICAL

**Mitigations:**
- Remove port exposure
- Implement authentication
- Add rate limiting
- Enable TLS
- Monitor for unusual query patterns

---

### Scenario 2: Compromised Container - Lateral Movement
**Attack Path:**
1. Attacker exploits vulnerability in agent-app dependency
2. Gains code execution in agent-app container
3. Enumerates Docker network: discovers chroma container
4. Directly accesses ChromaDB API (no authentication)
5. Modifies memories to inject false information
6. Poisons embedding space with misleading data
7. Establishes persistence via scheduled task or backdoor

**Likelihood:** MEDIUM
**Impact:** CRITICAL
**Risk:** HIGH

**Mitigations:**
- Container hardening (non-root, dropped capabilities)
- Network segmentation
- Service-to-service authentication
- Intrusion detection
- Regular vulnerability scanning

---

### Scenario 3: NoSQL Injection - Privilege Escalation
**Attack Path:**
1. Attacker controls conversation_id or other filter parameter
2. Crafts malicious metadata filter with operators like $where, $regex
3. Bypasses confidence threshold via filter manipulation
4. Retrieves memories from other conversations
5. Modifies query to cause resource exhaustion
6. Exploits ChromaDB vulnerability via malicious query
7. Achieves code execution in ChromaDB container

**Likelihood:** MEDIUM
**Impact:** HIGH
**Risk:** HIGH

**Mitigations:**
- Strict input validation
- Metadata filter allowlist
- Query complexity limits
- ChromaDB security updates
- Web application firewall (WAF)

---

### Scenario 4: Man-in-the-Middle - Data Manipulation
**Attack Path:**
1. Attacker compromises another container on Docker network
2. Performs ARP spoofing to intercept agent-app → ChromaDB traffic
3. Captures HTTP requests containing sensitive data
4. Modifies requests in transit (e.g., change confidence scores)
5. Injects false memories into responses
6. Steals any authentication credentials (if implemented later)

**Likelihood:** MEDIUM
**Impact:** HIGH
**Risk:** MEDIUM

**Mitigations:**
- Enable TLS for all communication
- Network encryption
- Mutual TLS authentication
- Network monitoring
- Container isolation

---

### Scenario 5: Supply Chain Attack - Backdoor Insertion
**Attack Path:**
1. Attacker compromises PyPI package used by agent-app
2. Malicious code injected into dependency update
3. Agent-app pulls compromised dependency during build
4. Backdoor activates on container start
5. Exfiltrates data to external C2 server
6. Establishes persistent access
7. Spreads to other containers

**Likelihood:** LOW
**Impact:** CRITICAL
**Risk:** MEDIUM

**Mitigations:**
- Pin dependency versions with hashes
- Automated dependency scanning
- Supply chain security tools
- Code signing
- Network egress filtering

---

## Risk Assessment Matrix

| Threat | Likelihood | Impact | Risk Score | Priority |
|--------|------------|--------|------------|----------|
| Exposed ChromaDB port exploitation | HIGH | CRITICAL | 10 | P0 |
| Unencrypted HTTP traffic interception | HIGH | HIGH | 9 | P0 |
| No service-to-service authentication | MEDIUM | HIGH | 8 | P1 |
| NoSQL injection via metadata filters | MEDIUM | HIGH | 8 | P1 |
| Container running as root | MEDIUM | HIGH | 8 | P1 |
| Insufficient rate limiting | HIGH | MEDIUM | 7 | P1 |
| Sensitive data in logs | HIGH | MEDIUM | 7 | P2 |
| No request size limits | MEDIUM | MEDIUM | 6 | P2 |
| Container escape vulnerabilities | LOW | CRITICAL | 6 | P2 |
| Supply chain attacks | LOW | CRITICAL | 6 | P2 |
| Unencrypted data at rest | MEDIUM | MEDIUM | 6 | P3 |
| Error message information disclosure | MEDIUM | LOW | 4 | P3 |
| Insufficient security logging | HIGH | LOW | 4 | P3 |
| SSRF via MCP endpoint | LOW | MEDIUM | 3 | P4 |
| Embedding poisoning | LOW | MEDIUM | 3 | P4 |

**Risk Score Calculation:**
- Likelihood: LOW=1, MEDIUM=3, HIGH=5
- Impact: LOW=1, MEDIUM=3, HIGH=5, CRITICAL=7
- Risk Score = Likelihood × Impact

**Priority:**
- P0: Critical (Fix immediately) - Score 9-10
- P1: High (Fix in days) - Score 7-8
- P2: Medium (Fix in weeks) - Score 5-6
- P3: Low (Fix in months) - Score 3-4
- P4: Informational (Monitor) - Score 1-2

---

## Security Controls Mapping

### Preventive Controls

| Control | Threats Addressed | Status | Priority |
|---------|-------------------|--------|----------|
| Input validation | Injection, DoS | PARTIAL | P0 |
| TLS encryption | MITM, information disclosure | NOT IMPLEMENTED | P0 |
| Service authentication | Spoofing, unauthorized access | NOT IMPLEMENTED | P0 |
| Rate limiting | DoS | PARTIAL | P1 |
| Container hardening | Privilege escalation | NOT IMPLEMENTED | P1 |
| Network segmentation | Lateral movement | NOT IMPLEMENTED | P1 |
| Request size limits | DoS | PARTIAL | P2 |
| Dependency pinning | Supply chain | NOT IMPLEMENTED | P2 |

### Detective Controls

| Control | Threats Detected | Status | Priority |
|---------|------------------|--------|----------|
| Security event logging | All threats | PARTIAL | P2 |
| Anomaly detection | DoS, injection | NOT IMPLEMENTED | P3 |
| Vulnerability scanning | Dependency vulnerabilities | NOT IMPLEMENTED | P2 |
| Network monitoring | MITM, lateral movement | NOT IMPLEMENTED | P3 |
| File integrity monitoring | Tampering | NOT IMPLEMENTED | P3 |

### Corrective Controls

| Control | Purpose | Status | Priority |
|---------|---------|--------|----------|
| Incident response plan | Rapid response | NOT IMPLEMENTED | P2 |
| Backup and restore | Data recovery | NOT IMPLEMENTED | P2 |
| Container restart policy | Availability | IMPLEMENTED | P4 |
| Log aggregation | Forensics | NOT IMPLEMENTED | P3 |

---

## Deployment Environment Considerations

### Development Environment
**Risk Tolerance:** MEDIUM
- Local laptop/workstation
- No external network exposure
- Single developer access
- **Acceptable Risks:** Unencrypted data at rest, exposed ports for debugging

**Required Controls:**
- Input validation
- Rate limiting (to prevent accidental DoS)
- Basic security logging

---

### Staging/QA Environment
**Risk Tolerance:** MEDIUM-LOW
- Internal network
- Multiple team member access
- May contain production-like data
- **Acceptable Risks:** Self-signed TLS certificates, localhost-bound ports

**Required Controls:**
- TLS encryption
- Service authentication
- Container hardening
- Security logging
- Rate limiting
- Input validation

---

### Production Environment
**Risk Tolerance:** LOW
- Public or semi-public network
- Handles sensitive user data
- High availability requirements
- **Acceptable Risks:** None for HIGH/CRITICAL threats

**Required Controls:**
- All preventive controls
- All detective controls
- All corrective controls
- Compliance requirements (GDPR, CCPA, etc.)
- Regular security audits
- Penetration testing

---

## Threat Model Maintenance

### Review Schedule
- **Quarterly:** Review threat model for changes in architecture
- **Per Release:** Update threat model for new features
- **Post-Incident:** Update based on lessons learned
- **Annual:** Comprehensive threat modeling workshop

### Update Triggers
- New components added to architecture
- New external integrations
- Changes in deployment environment
- Discovery of new vulnerability classes
- Regulatory/compliance changes

### Responsibility
- **Security Engineer:** Maintain threat model
- **Development Team:** Report architecture changes
- **Operations Team:** Report deployment changes
- **Chief of Staff:** Approve risk acceptance decisions

---

## Conclusion

This threat model identifies **10 CRITICAL/HIGH risk** threats that should be addressed before production deployment:

1. Exposed ChromaDB port (P0)
2. Unencrypted HTTP traffic (P0)
3. No service authentication (P1)
4. NoSQL injection risk (P1)
5. Container running as root (P1)
6. Insufficient rate limiting (P1)
7. Sensitive data in logs (P2)
8. No request size limits (P2)
9. Container escape vulnerabilities (P2)
10. Supply chain attacks (P2)

The current implementation is suitable for **internal development** use but requires significant security hardening for production deployment. Follow the Security Recommendations document for detailed mitigation guidance.

**Risk Acceptance:** For V1 internal tool use, the following risks are documented and accepted:
- Unencrypted data at rest (INFORMATIONAL)
- Error message information disclosure (LOW)
- Basic security logging (LOW)

All other identified risks should be mitigated according to the priority schedule.
