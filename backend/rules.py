"""Danger rule engine (v2).

Rules live in rules.yaml (see the comments there). Compared with the v1 CSV rules:
  * conditions use label groups (any-of), plus all / any / none clauses
  * every condition needs a minimum probability, and the rule confidence is the
    weakest condition -> risk_score = 1 - prod(1 - severity * confidence)
  * temporal persistence: a rule must hold on `min_hits` consecutive evaluations
    and is released only after `release` misses (no flicker, fewer false alarms)
  * a weighted face-concealment score catches combinations no rule lists explicitly
The legacy dangerous_attributes_rules.csv is still accepted (exact all-of rules).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import yaml

LEVEL_ORDER = ["Low", "Medium", "Medium-High", "High"]
LEGACY_SEVERITY = {"High": 0.85, "Medium-High": 0.7, "Medium": 0.5}


@dataclass
class Rule:
    id: str
    desc: str
    category: str
    risk: str
    severity: float
    all: list[str]
    any: list[str]
    none: list[str]
    min_conf: float
    min_hits: int
    release: int
    min_level: str = "Medium"     # floor for the risk level when this rule is active


@dataclass
class RuleState:
    """Per-track persistence counters."""
    hits: dict[str, int] = field(default_factory=dict)
    misses: dict[str, int] = field(default_factory=dict)
    last: dict[str, dict] = field(default_factory=dict)   # rule id -> last matched payload


@dataclass
class DangerResult:
    matched: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)
    risk_score: float = 0.0
    risk_level: str = "Low"
    concealment: float = 0.0

    @property
    def is_dangerous(self) -> bool:
        return bool(self.matched)

    @property
    def labels(self) -> set[str]:
        return {l for r in self.matched for l in r["conditions"]}

    def to_json(self) -> dict:
        return {
            "is_dangerous": self.is_dangerous,
            "risk_level": self.risk_level,
            "risk_score": round(self.risk_score, 3),
            "concealment_score": round(self.concealment, 3),
            "matched_rules": self.matched,
            "pending_rules": self.pending,
            "danger_labels": sorted(self.labels),
        }


class RuleEngine:
    def __init__(self, path: Path):
        self.path = path
        if path.suffix.lower() == ".csv":
            self._load_csv(path)
        else:
            self._load_yaml(path)

    # -- loading ----------------------------------------------------------- #
    def _load_yaml(self, path: Path):
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        d = cfg.get("defaults", {})
        self.levels = cfg.get("levels", {"High": 0.75, "Medium-High": 0.55, "Medium": 0.35})
        self.context = cfg.get("context", {})
        self.behavior = cfg.get("behavior", {}) or {}
        conc = cfg.get("concealment", {})
        self.conc_weights: dict[str, float] = conc.get("weights", {})
        self.conc_threshold = float(conc.get("threshold", 0.7))
        self.concealed_threshold = float(conc.get("concealed_threshold", 0.45))
        self.groups: dict[str, list[str]] = cfg.get("groups", {})
        self.rules = [
            Rule(id=str(r["id"]), desc=r["desc"], category=r.get("category", ""), risk=r.get("risk", "Medium"),
                 severity=float(r.get("severity", LEGACY_SEVERITY.get(r.get("risk"), 0.6))),
                 all=list(r.get("all", [])), any=list(r.get("any", [])), none=list(r.get("none", [])),
                 min_conf=float(r.get("min_conf", d.get("min_conf", 0.45))),
                 min_hits=int(r.get("min_hits", d.get("min_hits", 2))),
                 release=int(r.get("release", d.get("release", 3))),
                 min_level=r.get("min_level", "Medium"))
            for r in cfg.get("rules", [])
        ]
        for r in self.rules:  # validate group references early
            for c in r.all + r.any + r.none:
                self.expand(c)

    def _load_csv(self, path: Path):
        self.levels = {"High": 0.75, "Medium-High": 0.55, "Medium": 0.35}
        self.context, self.groups, self.conc_weights, self.behavior = {}, {}, {}, {}
        self.conc_threshold, self.concealed_threshold = 1.1, 1.1
        self.rules = []
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                cond = row["Rule_Condition"].replace("{", "").replace("}", "")
                conds = [c.strip() for c in cond.split(",") if c.strip()]
                risk = row["Risk_Level"].strip()
                self.rules.append(Rule(row["Rule_ID"].strip(), row["Description"].strip(), row["Category"].strip(),
                                       risk, LEGACY_SEVERITY.get(risk, 0.6), conds, [], [], 0.0, 1, 1))

    def expand(self, name: str, _seen: frozenset = frozenset()) -> set[str]:
        """Group name -> set of concrete labels (groups may nest)."""
        if name not in self.groups:
            return {name}
        if name in _seen:
            raise ValueError(f"Cyclic group reference: {name}")
        out: set[str] = set()
        for item in self.groups[name]:
            out |= self.expand(item, _seen | {name})
        return out

    # -- scoring ----------------------------------------------------------- #
    def concealment_score(self, probs: dict[str, float]) -> float:
        """probs: label -> probability for *selected* labels."""
        keep = 1.0
        for label, w in self.conc_weights.items():
            keep *= 1.0 - float(w) * probs.get(label, 0.0)
        return 1.0 - keep

    def _cond(self, cond: str, active: dict[str, float], min_conf: float) -> tuple[float, str] | None:
        best = None
        for label in self.expand(cond):
            p = active.get(label)
            if p is not None and p >= min_conf and (best is None or p > best[0]):
                best = (p, label)
        return best

    def _match(self, rule: Rule, active: dict[str, float]) -> tuple[float, list[str]] | None:
        evidence, confs = [], []
        for c in rule.all:
            hit = self._cond(c, active, rule.min_conf)
            if hit is None:
                return None
            confs.append(hit[0])
            evidence.append(hit[1])
        if rule.any:
            hits = [h for h in (self._cond(c, active, rule.min_conf) for c in rule.any) if h]
            if not hits:
                return None
            best = max(hits)
            confs.append(best[0])
            evidence.append(best[1])
        if any(self._cond(c, active, 0.0) for c in rule.none):
            return None
        return (min(confs) if confs else 1.0), evidence

    def evaluate(self, active: dict[str, float], state: RuleState | None = None, instant: bool = False) -> DangerResult:
        """active: selected label -> probability (attributes + cues + context labels).

        instant=True ignores min_hits (single image, no time axis).
        """
        state = state or RuleState()
        res = DangerResult(concealment=self.concealment_score(active))
        for rule in self.rules:
            m = self._match(rule, active)
            if m is not None:
                state.hits[rule.id] = state.hits.get(rule.id, 0) + 1
                state.misses[rule.id] = 0
                conf, evidence = m
                state.last[rule.id] = {"id": rule.id, "category": rule.category, "risk": rule.risk, "desc": rule.desc,
                                       "conditions": evidence, "confidence": round(float(conf), 3),
                                       "severity": rule.severity, "min_level": rule.min_level}
            else:
                state.misses[rule.id] = state.misses.get(rule.id, 0) + 1
                if state.misses[rule.id] >= rule.release:
                    state.hits[rule.id] = 0
                    state.last.pop(rule.id, None)
            hits = state.hits.get(rule.id, 0)
            if rule.id in state.last and hits >= (1 if instant else rule.min_hits):
                res.matched.append(state.last[rule.id])
            elif m is not None:
                res.pending.append({"id": rule.id, "desc": rule.desc, "hits": hits, "need": rule.min_hits})

        keep = 1.0
        for r in res.matched:
            keep *= 1.0 - r["severity"] * r["confidence"]
        res.risk_score = 1.0 - keep
        if res.matched:
            res.risk_level = max((r["min_level"] for r in res.matched), key=LEVEL_ORDER.index)
            for level in ("High", "Medium-High", "Medium"):
                if res.risk_score >= float(self.levels.get(level, 1.1)):
                    res.risk_level = max(res.risk_level, level, key=LEVEL_ORDER.index)
                    break
        res.matched.sort(key=lambda r: -r["severity"] * r["confidence"])
        return res
