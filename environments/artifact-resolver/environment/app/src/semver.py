"""Semantic version parsing, constraint validation, and range matching."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, raw: str) -> "SemVer":
        parts = raw.strip().split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(f"invalid semantic version: {raw}")
        return cls(int(parts[0]), int(parts[1]), int(parts[2]))

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class VersionConstraint:
    _OPERATORS = (">=", "<=", "!=", "==", ">", "<", "^", "~")

    def __init__(self, expr: str) -> None:
        self.expr = expr.strip()
        if not self.expr:
            raise ValueError("empty version constraint")
        self._clauses: list[tuple[str, SemVer | None]] = []
        for raw in self.expr.split(","):
            tok = raw.strip()
            if not tok:
                raise ValueError(f"empty clause in constraint: {expr}")
            if tok == "*":
                self._clauses.append(("*", None))
            else:
                op = next((o for o in self._OPERATORS if tok.startswith(o)), None)
                self._clauses.append((op or "==", SemVer.parse(tok[len(op):] if op else tok)))

    def matches(self, candidate: SemVer) -> bool:
        for op, base in self._clauses:
            if op == "*":
                continue
            assert base is not None
            ok = {
                ">=": candidate >= base, "<=": candidate <= base, "!=": candidate != base,
                "==": candidate == base, ">": candidate > base, "<": candidate < base,
                "^": base <= candidate < SemVer(base.major + 1, 0, 0),
                "~": base <= candidate < SemVer(base.major, base.minor + 1, 0),
            }[op]
            if not ok:
                return False
        return True

    def intersect(self, other: "VersionConstraint") -> "VersionConstraint":
        return VersionConstraint(f"{self.expr}, {other.expr}")

    def filter_compatible(self, versions: list[SemVer]) -> list[SemVer]:
        return sorted(v for v in versions if self.matches(v))

    def select_highest(self, versions: list[SemVer]) -> SemVer | None:
        compatible = self.filter_compatible(versions)
        return compatible[-1] if compatible else None
