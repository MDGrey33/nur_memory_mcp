"""Privacy filtering service (placeholder for v3)."""

import logging
from typing import List, Dict, Any


logger = logging.getLogger("mcp-memory.privacy")


class PrivacyFilterService:
    """
    Privacy filtering service for v2 (placeholder implementation).

    In v2, this always allows access. Privacy enforcement will be
    implemented in v3 with multi-user support.
    """

    def filter_results(
        self,
        results: List[Any],
        user_context: Dict[str, Any]
    ) -> List[Any]:
        """
        Filter results based on visibility/sensitivity.

        v2 behavior: Always allows all results.

        Args:
            results: List of search results
            user_context: User context (unused in v2)

        Returns:
            Unfiltered results (same as input)
        """
        # TODO v3: Implement sensitivity/visibility checks
        logger.debug(f"Privacy filter: allowing all {len(results)} results (v2 placeholder)")
        return results

    def can_access_artifact(
        self,
        artifact_metadata: Dict[str, Any],
        user_context: Dict[str, Any]
    ) -> bool:
        """
        Check if user can access artifact.

        v2 behavior: Always returns True.

        Args:
            artifact_metadata: Artifact metadata with sensitivity/visibility
            user_context: User context (unused in v2)

        Returns:
            True (always allows in v2)
        """
        # TODO v3: Check user_context against artifact visibility_scope
        sensitivity = artifact_metadata.get("sensitivity", "normal")
        visibility_scope = artifact_metadata.get("visibility_scope", "me")

        logger.debug(
            f"Privacy check: sensitivity={sensitivity}, "
            f"visibility={visibility_scope}, allowed=True (v2 placeholder)"
        )

        return True
