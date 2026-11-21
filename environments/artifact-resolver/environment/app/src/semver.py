"""Minimal semantic version parsing and range matching."""

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

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class VersionConstraint:
    def __init__(self, expr: str) -> None:
        self.expr = expr.strip()
        if not self.expr:
            raise ValueError("empty version constraint")

    def matches(self, candidate: SemVer) -> bool:
        for clause in self.expr.split(","):
            token = clause.strip()
            if token.startswith(">="):
                if candidate < SemVer.parse(token[2:]):
                    return False
            elif token.startswith("<"):
                if not (candidate < SemVer.parse(token[1:])):
                    return False
            elif token.startswith("^"):
                base = SemVer.parse(token[1:])
                upper = SemVer(base.major + 1, 0, 0)
                if candidate < base or not (candidate < upper):
                    return False
            elif token.startswith("=="):
                if candidate != SemVer.parse(token[2:]):
                    return False
            else:
                if candidate != SemVer.parse(token):
                    return False
        return True

    def select_highest(self, versions: list[SemVer]) -> SemVer | None:
        compatible = [v for v in versions if self.matches(v)]
        return max(compatible) if compatible else None
