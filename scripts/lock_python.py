"""Record installed direct and transitive dependencies from the selected inputs."""
from collections import deque
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1] / "backend"


def inputs(path: Path) -> list[Requirement]:
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("-r "):
            result.extend(inputs(path.parent / line[3:]))
        elif line and not line.startswith("#"):
            result.append(Requirement(line))
    return result


def lock(source: str, destination: str) -> None:
    queue = deque(inputs(ROOT / source))
    selected = {}
    visited = set()
    while queue:
        requirement = queue.popleft()
        name = canonicalize_name(requirement.name)
        state = (name, tuple(sorted(requirement.extras)))
        if state in visited:
            continue
        visited.add(state)
        package = distribution(name)
        selected[name] = package.version
        for value in package.requires or []:
            child = Requirement(value)
            contexts = requirement.extras or {""}
            if child.marker is None or any(
                child.marker.evaluate({"extra": extra}) for extra in contexts
            ):
                queue.append(child)
    lines = ["# Generated from " + source + "; install this exact dependency set."]
    lines.extend(name + "==" + version for name, version in sorted(selected.items()))
    (ROOT / destination).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(destination + ": " + str(len(selected)) + " pinned packages")


lock("requirements.in", "requirements.txt")
lock("requirements-dev.in", "requirements-dev.txt")
