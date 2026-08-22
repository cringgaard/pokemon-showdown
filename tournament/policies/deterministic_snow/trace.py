"""Structured, serializable decision traces for later policy phases."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .actions import CanonicalLegalAction
from .features import FEATURES_BY_ID
from .serialization import canonical_json, parse_json, to_primitive


class TraceLevel(str, Enum):
	NONE = "NONE"
	SUMMARY = "SUMMARY"
	TOP_CANDIDATES = "TOP_CANDIDATES"
	FULL = "FULL"


@dataclass(frozen=True)
class TraceVersions:
	policy: str
	config: str
	weights: str
	mechanics: str
	team: str
	format: str
	mod: str


@dataclass(frozen=True)
class RuntimeStrategyScores:
	glaceon_fortress: float
	aggron_fortress: float
	tactical_offense: float
	primary_plan: str | None


@dataclass(frozen=True)
class OpponentResponseHypothesis:
	id: str
	weight: float
	reasons: tuple[str, ...]
	actions: tuple[str, ...]


@dataclass(frozen=True)
class FeatureContribution:
	feature_id: str
	value: float
	weight: float
	contribution: float


@dataclass(frozen=True)
class TacticalRuleAdjustment:
	rule_id: str
	adjustment: float
	reason: str


@dataclass(frozen=True)
class ResponseEvaluationTrace:
	response_id: str
	utility: float
	confidence: str
	feature_contributions: tuple[FeatureContribution, ...]


@dataclass(frozen=True)
class CandidateActionTrace:
	action: CanonicalLegalAction
	expected_score: float | None
	credible_bad_case_score: float | None
	best_case_score: float | None
	final_score: float | None
	response_evaluations: tuple[ResponseEvaluationTrace, ...]
	feature_contributions: tuple[FeatureContribution, ...]
	tactical_adjustments: tuple[TacticalRuleAdjustment, ...]


@dataclass(frozen=True)
class TraceRuntime:
	latency_ms: float
	candidate_count: int
	response_count: int
	evaluation_count: int


@dataclass(frozen=True)
class DecisionTrace:
	schema_version: int
	level: TraceLevel
	decision_id: int
	turn: int
	versions: TraceVersions
	strategy: RuntimeStrategyScores | None
	major_threats: tuple[str, ...]
	opponent_responses: tuple[OpponentResponseHypothesis, ...]
	candidates: tuple[CandidateActionTrace, ...]
	selected_action_id: str | None
	runtime: TraceRuntime

	def validate(self) -> None:
		if self.schema_version != 1:
			raise ValueError("DecisionTrace.schema_version must be 1")
		if self.decision_id < 0 or self.turn < 0:
			raise ValueError("Trace decision and turn identifiers must be non-negative")
		for name, version in vars(self.versions).items():
			if not isinstance(version, str) or not version:
				raise ValueError(f"Trace version {name} must be a non-empty string")
		if self.strategy:
			for name in ("glaceon_fortress", "aggron_fortress", "tactical_offense"):
				value = getattr(self.strategy, name)
				if not _finite(value) or value < 0 or value > 100:
					raise ValueError(f"Strategy score {name} must be between zero and 100")
		candidate_ids = {candidate.action.action_id for candidate in self.candidates}
		if len(candidate_ids) != len(self.candidates):
			raise ValueError("Candidate action IDs must be unique")
		if self.selected_action_id is not None and self.selected_action_id not in candidate_ids:
			raise ValueError("selected_action_id must identify a traced candidate")
		for response in self.opponent_responses:
			if not response.id or not _finite(response.weight) or response.weight < 0:
				raise ValueError("Opponent response IDs and weights must be valid")
		for candidate in self.candidates:
			for score in (candidate.expected_score, candidate.credible_bad_case_score, candidate.best_case_score, candidate.final_score):
				if score is not None and not _finite(score):
					raise ValueError("Candidate scores must be finite when present")
			for contribution in (*candidate.feature_contributions, *(
				item for response in candidate.response_evaluations for item in response.feature_contributions
			)):
				if contribution.feature_id not in FEATURES_BY_ID:
					raise ValueError(f"Unknown trace feature ID: {contribution.feature_id}")
				if not all(_finite(value) for value in (contribution.value, contribution.weight, contribution.contribution)):
					raise ValueError("Feature contributions must be finite")
			for response in candidate.response_evaluations:
				if not response.response_id or not _finite(response.utility) or not response.confidence:
					raise ValueError("Response evaluations must contain valid IDs, utilities, and confidence")
			for adjustment in candidate.tactical_adjustments:
				if not adjustment.rule_id or not adjustment.reason or not _finite(adjustment.adjustment):
					raise ValueError("Tactical rule adjustments must be finite and documented")
		if self.runtime.latency_ms < 0 or any(value < 0 for value in (
			self.runtime.candidate_count, self.runtime.response_count, self.runtime.evaluation_count,
		)):
			raise ValueError("Trace runtime values must be non-negative")

	def to_dict(self) -> dict[str, Any]:
		return {name: to_primitive(getattr(self, name)) for name in self.__dataclass_fields__}

	def to_json(self) -> str:
		self.validate()
		return canonical_json(self)

	@classmethod
	def empty(
		cls,
		*,
		decision_id: int,
		turn: int,
		versions: TraceVersions,
		level: TraceLevel = TraceLevel.SUMMARY,
	) -> "DecisionTrace":
		return cls(1, level, decision_id, turn, versions, None, (), (), (), None, TraceRuntime(0, 0, 0, 0))

	@classmethod
	def from_json(cls, value: str) -> "DecisionTrace":
		return cls.from_dict(_mapping(parse_json(value), "DecisionTrace"))

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "DecisionTrace":
		strategy_value = value.get("strategy")
		trace = cls(
			value["schema_version"], TraceLevel(value["level"]), value["decision_id"], value["turn"],
			TraceVersions(**value["versions"]),
			RuntimeStrategyScores(**strategy_value) if strategy_value is not None else None,
			tuple(value["major_threats"]),
			tuple(OpponentResponseHypothesis(
				item["id"], item["weight"], tuple(item["reasons"]), tuple(item["actions"])
			) for item in value["opponent_responses"]),
			tuple(_candidate_from_dict(item) for item in value["candidates"]),
			value.get("selected_action_id"), TraceRuntime(**value["runtime"]),
		)
		trace.validate()
		return trace


def _candidate_from_dict(value: Mapping[str, Any]) -> CandidateActionTrace:
	return CandidateActionTrace(
		CanonicalLegalAction.from_dict(value["action"]), value.get("expected_score"),
		value.get("credible_bad_case_score"), value.get("best_case_score"), value.get("final_score"),
		tuple(ResponseEvaluationTrace(
			item["response_id"], item["utility"], item["confidence"],
			tuple(FeatureContribution(**contribution) for contribution in item["feature_contributions"]),
		) for item in value["response_evaluations"]),
		tuple(FeatureContribution(**item) for item in value["feature_contributions"]),
		tuple(TacticalRuleAdjustment(**item) for item in value["tactical_adjustments"]),
	)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
	if not isinstance(value, Mapping):
		raise ValueError(f"{label} must be an object")
	return value


def _finite(value: Any) -> bool:
	return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
