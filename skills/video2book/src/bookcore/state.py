"""Input fingerprints and read-only task evaluation, independent of domain plans."""
from dataclasses import asdict
from pathlib import Path

from .contracts import Issue, Report, Task
from .io import exclusive_lock, file_digest, fingerprint, read_json, relative_path, write_json

STATE_FILE = "production_state.json"


def _load(workspace):
    path = relative_path(workspace, STATE_FILE)
    if not path.exists():
        return {"schema_version": 1, "tasks": {}}
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("tasks"), dict):
        raise ValueError("Unsupported production_state.json schema")
    return data


def inputs(workspace, task):
    return {name: file_digest(relative_path(workspace, name)) for name in task.inputs}


def signature(workspace, task):
    return _signature(task, inputs(workspace, task))


def _signature(task, input_hashes):
    return fingerprint({"task": asdict(task), "inputs": input_hashes})


def register(workspace: Path, tasks, *, replace_prefix=None) -> None:
    with exclusive_lock(relative_path(workspace, ".production-state.lock")):
        _register(workspace, tasks, replace_prefix=replace_prefix)


def _register(workspace, tasks, *, replace_prefix):
    """Refresh task inputs; re-export alone never approves an unchanged old output."""
    data = _load(workspace)
    tasks = list(tasks)
    if len({t.task_id for t in tasks}) != len(tasks):
        raise ValueError("Duplicate task IDs")
    if replace_prefix is not None:
        ids = {t.task_id for t in tasks}
        data["tasks"] = {key: value for key, value in data["tasks"].items()
                         if not key.startswith(replace_prefix) or key in ids}
    for task in tasks:
        output = relative_path(workspace, task.output)
        input_hashes = inputs(workspace, task)
        sig = _signature(task, input_hashes)
        old = data["tasks"].get(task.task_id)
        record = {"spec": asdict(task), "signature": sig, "input_hashes": input_hashes}
        if old and old["signature"] == sig:
            record = old
        elif output.is_file():
            record["previous_output"] = file_digest(output)
            # Legacy products remain readable, but are never certified as fresh.
            record["legacy"] = old is None
        data["tasks"][task.task_id] = record
    write_json(relative_path(workspace, STATE_FILE), data)


def statuses(workspace: Path, *, only_output=None) -> list[dict]:
    result = []
    for task_id, record in _load(workspace)["tasks"].items():
        task = Task(**record["spec"])
        if only_output is not None and task.output != only_output:
            continue
        output = relative_path(workspace, task.output)
        current = file_digest(output)
        input_hashes = inputs(workspace, task)
        missing = any(value is None for value in input_hashes.values())
        if missing:
            state = "blocked"
        elif _signature(task, input_hashes) != record["signature"]:
            state = "stale"
        elif current is None:
            state = "pending"
        elif current == record.get("previous_output"):
            state = "unverified" if record.get("legacy") else "stale"
        else:
            state = "ready"
        result.append({"task_id": task_id, "output": task.output, "state": state,
                       "required": task.required, "exists": current is not None})
    return result


def report(workspace: Path, tool: str, *, active_outputs=None) -> Report:
    result = Report(tool)
    if not relative_path(workspace, STATE_FILE).exists():
        result.issues.append(Issue("untracked", "Legacy workspace has no input receipts", severity="warning"))
        return result
    for item in statuses(workspace):
        if active_outputs is not None and item["output"] not in active_outputs:
            continue
        if not item["required"] and not item["exists"]:
            continue
        state = item["state"]
        if state != "ready":
            result.issues.append(Issue("task_" + state, "Re-export task and complete or review its output",
                                       item["output"], "warning" if state == "unverified" else "error"))
    return result


def task_from_paths(workspace, task_id, output, paths, *, metadata=None, required=True):
    root = Path(workspace).resolve()
    return Task(task_id, Path(output).resolve().relative_to(root).as_posix(),
                tuple(Path(p).resolve().relative_to(root).as_posix() for p in paths),
                metadata, required)


def output_is_current(workspace, output):
    name = Path(output).resolve().relative_to(Path(workspace).resolve()).as_posix()
    matches = statuses(workspace, only_output=name)
    return not matches or all(t["state"] in ("ready", "unverified") for t in matches)


def retain(workspace, prefix, task_ids):
    """Retire only tasks omitted from a complete new domain plan."""
    with exclusive_lock(relative_path(workspace, ".production-state.lock")):
        data = _load(workspace)
        data["tasks"] = {key: value for key, value in data["tasks"].items()
                         if not key.startswith(prefix) or key in task_ids}
        write_json(relative_path(workspace, STATE_FILE), data)


def activate(workspace, task_id):
    """Bind newly available inputs before first dispatch, never accept changed inputs."""
    path = relative_path(workspace, STATE_FILE)
    if not path.exists():
        return
    with exclusive_lock(relative_path(workspace, ".production-state.lock")):
        record = _load(workspace)["tasks"].get(task_id)
        if record is None:
            return
        task = Task(**record["spec"])
        before = record.get("input_hashes", {})
        now = inputs(workspace, task)
        if (before and any(v is None for v in before.values())
                and all(v is not None for v in now.values())
                and all(value is None or now.get(name) == value for name, value in before.items())
                and not relative_path(workspace, task.output).exists()):
            _register(workspace, [task], replace_prefix=None)
