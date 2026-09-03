"""Push-triggered incremental analysis helpers (spec sections 51, Phase 19).

``RunMode.INCREMENTAL`` runs a sandbox-free subset of the pipeline over a new snapshot and
scopes the change-impact / test-gap output to the components on the webhook's changed
files. ``scope.resolve_changed_components`` is the file-path -> component-id resolver.
"""

from archon.analysis.incremental.scope import resolve_changed_components

__all__ = ["resolve_changed_components"]
