"""Video-domain policy for the shared production kernel."""
from src.bookcore.contracts import Product, Profile
from src.bookcore.checks import check_products
from src.bookcore.state import report, statuses

PROFILE = Profile("video2book", (
    Product("textbooks", ("*_精读全书.md",), True),
    Product("notes", ("*_笔记.md",), True, 1000),
    Product("subtitles", ("*_逐字稿.md", "*_clean.txt", "*_supplement.txt"),
            True, preserve_existing=True),
), read_only_target=True)


def production_report(workspace):
    result = check_products(workspace, PROFILE)
    result.issues.extend(report(workspace, PROFILE.tool).issues)
    return result


def production_status(workspace):
    return {**production_report(workspace).as_dict(), "tasks": statuses(workspace),
            "scope": "products_and_fingerprints"}
