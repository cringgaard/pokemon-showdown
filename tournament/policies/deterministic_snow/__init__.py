"""Foundations for the deterministic snow-team policy.

B1 intentionally exposes data models and deterministic transformations only.
It does not provide a ``choose_action`` implementation.
"""

from .actions import CanonicalLegalAction, canonicalize_legal_action, canonicalize_legal_actions
from .config import PolicyConfig, default_config
from .features import FEATURE_REGISTRY, FeatureDefinition, FeatureFamily
from .knowledge import KnowledgeState, build_knowledge_state
from .trace import DecisionTrace

__all__ = [
	"CanonicalLegalAction",
	"DecisionTrace",
	"FEATURE_REGISTRY",
	"FeatureDefinition",
	"FeatureFamily",
	"KnowledgeState",
	"PolicyConfig",
	"build_knowledge_state",
	"canonicalize_legal_action",
	"canonicalize_legal_actions",
	"default_config",
]
