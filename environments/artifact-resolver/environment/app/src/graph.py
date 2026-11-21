"""Deterministic Kahn topological sort over package dependency graphs."""

from __future__ import annotations

from collections import deque


class CycleError(ValueError):
    """Raised when a dependency graph contains a cycle."""


class DependencyGraph:
    def __init__(self) -> None:
        self._deps: dict[str, set[str]] = {}

    def add_node(self, pkg: str) -> None:
        self._deps.setdefault(pkg, set())

    def add_dependency(self, dependent: str, dependency: str) -> None:
        self.add_node(dependent)
        self.add_node(dependency)
        self._deps[dependent].add(dependency)

    def topological_order(self) -> list[str]:
        in_degree: dict[str, int] = {node: 0 for node in self._deps}
        reverse_edges: dict[str, set[str]] = {node: set() for node in self._deps}
        for dependent, prereqs in self._deps.items():
            in_degree[dependent] = len(prereqs)
            for dep in prereqs:
                reverse_edges[dep].add(dependent)

        ready = deque(sorted(node for node, deg in in_degree.items() if deg == 0))
        ordered: list[str] = []
        while ready:
            current = ready.popleft()
            ordered.append(current)
            for consumer in sorted(reverse_edges[current]):
                in_degree[consumer] -= 1
                if in_degree[consumer] == 0:
                    ready.append(consumer)

        if len(ordered) != len(self._deps):
            raise CycleError("dependency cycle detected in manifest graph")
        return ordered
