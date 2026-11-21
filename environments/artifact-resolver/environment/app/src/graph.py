"""Deterministic Kahn topological sort and cycle diagnostics."""
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

    def nodes(self) -> tuple[str, ...]:
        return tuple(sorted(self._deps))

    def dependencies_of(self, pkg: str) -> tuple[str, ...]:
        return tuple(sorted(self._deps.get(pkg, ())))

    def find_cycle(self) -> list[str] | None:
        state, stack = {}, []

        def dfs(node: str) -> list[str] | None:
            state[node] = 1
            stack.append(node)
            for dep in sorted(self._deps.get(node, ())):
                if state.get(dep, 0) == 1:
                    return stack[stack.index(dep):] + [dep]
                if state.get(dep, 0) == 0 and (found := dfs(dep)) is not None:
                    return found
            stack.pop()
            state[node] = 2
            return None

        for node in sorted(self._deps):
            if state.get(node, 0) == 0 and (found := dfs(node)) is not None:
                return found
        return None

    def topological_order(self) -> list[str]:
        in_deg = {n: len(p) for n, p in self._deps.items()}
        rev: dict[str, set[str]] = {n: set() for n in self._deps}
        for dependent, prereqs in self._deps.items():
            for dep in prereqs:
                rev[dep].add(dependent)
        ready = deque(sorted(n for n, d in in_deg.items() if d == 0))
        ordered: list[str] = []
        while ready:
            cur = ready.popleft()
            ordered.append(cur)
            for consumer in sorted(rev[cur]):
                in_deg[consumer] -= 1
                if in_deg[consumer] == 0:
                    ready.append(consumer)
        if len(ordered) != len(self._deps):
            cycle = self.find_cycle()
            raise CycleError(f"dependency cycle detected: {' -> '.join(cycle) if cycle else 'cycle'}")
        return ordered
