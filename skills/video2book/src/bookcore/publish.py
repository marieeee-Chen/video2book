"""Validated local publication with a repository lock and exception rollback."""
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

from .checks import check_products
from .io import file_digest, read_json, relative_path, write_json, write_text

CATALOG = "course_catalog.json"
START, END = "<!-- course-catalog:start -->", "<!-- course-catalog:end -->"


def catalog_index(text, catalog):
    lines = [START, "## 分类浏览", ""]
    for category in sorted(catalog["categories"], key=lambda c: c["id"]):
        courses = sorted((c for c in catalog["courses"].values()
                          if c["category_paths"][0] == category["id"]), key=lambda c: c["publish_path"])
        if courses:
            lines += [f"### {category['name']}", ""]
            lines += [f"- [{c['title']}]({quote(c['publish_path'])}/)" for c in courses]
            lines.append("")
    lines.append(END)
    block = "\n".join(lines)
    if START in text and END in text:
        return text.split(START, 1)[0] + block + text.split(END, 1)[1]
    return text.rstrip() + "\n\n" + block + "\n"


def publish(workspace, root, publish_path, title, *, profile, subjects, validate, readme,
            direction="", tags=None, category="", prepare_candidate=None):
    if profile.read_only_target:
        raise ValueError(f"{profile.tool}: publication target is read-only")
    workspace, root = Path(workspace).resolve(), Path(root).resolve()
    course = relative_path(root, publish_path)
    if len(Path(publish_path).parts) != 2:
        raise ValueError("publish_path must be subject/course")
    if root.is_relative_to(workspace) or workspace.is_relative_to(course):
        raise ValueError("Workspace and publication target must not overlap")
    if any(p.is_symlink() for p in workspace.rglob("*")):
        raise ValueError("Publication inputs must not contain symlinks")
    if any(p.is_symlink() for p in course.rglob("*")):
        raise ValueError("Publication target must not contain symlinks")
    aliases = {name: key for key, name in subjects.items()}
    category = category or Path(publish_path).parts[0]
    category = aliases.get(category, category)
    if category not in subjects:
        raise ValueError(f"Unknown subject: {category}")
    check_products(workspace, profile).require()
    validate(workspace)
    root.mkdir(parents=True, exist_ok=True)
    lock = relative_path(root, ".production-publish.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"Another publication is active, or a stale lock needs review: {lock}") from exc
    os.close(fd)
    stage = None
    keep_stage = False
    try:
        catalog_path = relative_path(root, CATALOG)
        index_path = relative_path(root, "README.md")
        catalog = read_json(catalog_path) if catalog_path.exists() else {
            "schema_version": 2, "categories": [], "courses": {}}
        if catalog.get("schema_version") != 2 or not isinstance(catalog.get("courses"), dict):
            raise ValueError("Invalid catalog schema")
        course_id = course.name
        previous = catalog["courses"].get(course_id)
        if previous and previous["publish_path"] != publish_path:
            raise ValueError(f"Course ID already belongs to another path: {course_id}")
        entry = next((c for c in catalog["categories"] if c["id"] == category), None)
        if entry is None:
            catalog["categories"].append({"id": category, "name": subjects[category]})
        else:
            entry["name"] = subjects[category]
        catalog["courses"][course_id] = {
            "title": title, "direction": direction, "category_paths": [category],
            "tags": tags or [], "publish_path": publish_path}
        original = {p.name: p.read_bytes() if p.exists() else None for p in (catalog_path, index_path)}
        stage = Path(tempfile.mkdtemp(prefix=".publish-", dir=root))
        candidate, backup = stage / "course", stage / "previous"
        # Copy then prune so legacy preserve-existing policies can keep their exact files.
        if course.exists():
            shutil.copytree(course, candidate)
        else:
            candidate.mkdir()
        allowed = {p.directory for p in profile.products} | {"README.md"}
        for path in candidate.iterdir():
            if path.name not in allowed:
                shutil.rmtree(path) if path.is_dir() else path.unlink()
        files, copied, removed, observed = {}, {}, [], {}
        for product in profile.products:
            name = product.directory
            target = candidate / name
            sources = product.files(workspace)
            old = product.files(course)
            copied[name] = 0
            if product.preserve_existing and old:
                files[name] = old
                continue
            files[name] = sources
            observed.update({p: file_digest(p) for p in sources})
            if target.exists():
                removed.extend(f"{name}/{p.name}" for p in target.iterdir()
                               if p.name not in {s.name for s in sources})
                shutil.rmtree(target)
            if sources:
                target.mkdir()
            for source in sources:
                if file_digest(course / name / source.name) != observed[source]:
                    copied[name] += 1
                shutil.copy2(source, target / source.name)
        write_text(candidate / "README.md", readme(workspace, title, direction, files))
        if prepare_candidate is not None:
            prepare_candidate(candidate)
        removed = [name for name in removed if not (candidate / name).exists()]
        write_json(stage / CATALOG, catalog)
        write_text(stage / "README.md", catalog_index((original["README.md"] or b"").decode("utf-8"), catalog))
        if any(file_digest(p) != value for p, value in observed.items()):
            raise ValueError("Publication inputs changed while staging")
        for product in profile.products:
            if not (product.preserve_existing and product.files(course)):
                if product.files(workspace) != files[product.directory]:
                    raise ValueError("Publication product list changed while staging")
        validate(workspace)
        course.parent.mkdir(parents=True, exist_ok=True)
        installed = False
        try:
            if course.exists():
                course.rename(backup)
            candidate.rename(course)
            installed = True
            (stage / CATALOG).replace(catalog_path)
            (stage / "README.md").replace(index_path)
        except BaseException:
            try:
                if installed:
                    shutil.rmtree(course)
                if backup.exists():
                    backup.rename(course)
                for name, content in original.items():
                    if content is None:
                        (root / name).unlink(missing_ok=True)
                    else:
                        (root / name).write_bytes(content)
            except BaseException as recovery_error:
                keep_stage = True
                raise RuntimeError(f"Rollback failed; preserve recovery data at {stage}") from recovery_error
            raise
        total = {p.directory: len(p.files(course)) for p in profile.products}
        return {"course_dir": str(course), "course_id": course_id, "copied": copied,
                "removed": removed, "counts": total, "total": total,
                "catalog_courses": len(catalog["courses"])}
    finally:
        if stage is not None and not keep_stage:
            shutil.rmtree(stage)
        lock.unlink(missing_ok=True)
