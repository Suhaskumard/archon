"""Phase 3 - architecture reconstruction: role inference + coupling/centrality metrics."""

from archon.analysis.architecture.reconstruct import (
    ARCHITECTURE_VERSION,
    reconstruct_architecture,
)
from archon.analysis.architecture.roles import ROLE_VERSION, RoleContext, infer_role

__all__ = [
    "reconstruct_architecture",
    "infer_role",
    "RoleContext",
    "ROLE_VERSION",
    "ARCHITECTURE_VERSION",
]
