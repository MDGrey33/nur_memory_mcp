# ADR-001: Docker-First Deployment Approach

**Status:** Accepted

**Date:** 2025-12-25

**Context:**

The Chroma MCP Memory system requires persistent storage, multiple cooperating services, and the ability to run consistently across different environments (development, staging, production). We need to decide on a deployment strategy that balances ease of use, reliability, and operational simplicity.

Key considerations:
- Need for persistent storage (conversation history and memories)
- Multiple services that must coordinate (ChromaDB, chroma-mcp gateway, agent-app)
- Developer experience and ease of setup
- Production deployment requirements
- Service isolation and dependency management
- Cross-platform compatibility

Alternative approaches considered:
1. **Docker-first deployment** - All services containerized with Docker Compose
2. **Native installation** - Services installed directly on host system
3. **Kubernetes-first** - Deploy to K8s from the start
4. **Hybrid approach** - Some services containerized, others native

**Decision:**

We will adopt a **Docker-first deployment approach** for V1, using Docker Compose as the primary orchestration mechanism.

All services (ChromaDB, chroma-mcp, agent-app) will run as Docker containers with:
- Named Docker volumes for persistence (chroma_data)
- Docker network for service-to-service communication
- Environment variable-based configuration
- Health checks for dependency management
- Single `docker-compose.yml` as the deployment manifest

**Consequences:**

**Positive:**
- **Consistency**: Identical deployment across dev, staging, and production
- **Isolation**: Services run in isolated containers, reducing conflict
- **Simplicity**: Single command to start entire stack (`docker compose up`)
- **Persistence**: Docker volumes provide reliable, decoupled storage
- **Portability**: Works on any platform supporting Docker
- **Reproducibility**: Exact versions locked via image tags
- **Dependency management**: Service dependencies expressed declaratively
- **Easy cleanup**: Complete teardown with `docker compose down`

**Negative:**
- **Docker dependency**: Requires Docker and Docker Compose installed
- **Resource overhead**: Container overhead vs native processes
- **Learning curve**: Team must understand Docker concepts
- **Volume management**: Backups require Docker volume operations
- **Debugging complexity**: Container logs vs native process logs

**Migration path to production:**
- V1 uses Docker Compose (suitable for small-to-medium deployments)
- V2+ can migrate to Kubernetes using same container images
- Docker images can be pushed to registry for shared deployments
- Configuration via environment variables allows easy transition

**Implementation notes:**
- Use official ChromaDB image: `chromadb/chroma:latest`
- Use official chroma-mcp image: `ghcr.io/chroma-core/chroma-mcp:latest`
- Custom Dockerfile for agent-app
- Single persistent volume: `chroma_data` (only ChromaDB needs persistence)
- Internal Docker network for service communication
- Expose ports only when necessary (minimize surface area)

**Alternatives rejected:**

1. **Native installation**: Rejected due to environment inconsistency, difficult dependency management, and complex setup across different OS platforms.

2. **Kubernetes-first**: Rejected as over-engineering for V1. Kubernetes adds complexity (manifests, networking, storage classes) without proportional benefit at this scale. We can migrate to K8s later if needed.

3. **Hybrid approach**: Rejected due to complexity and loss of consistency benefits. Mixed deployment models increase operational burden and debugging difficulty.

**Related decisions:**
- ADR-002: ChromaDB as Vector Store
- ADR-004: Two-Collection Model

**Review date:** After V1 production deployment (3-6 months)
