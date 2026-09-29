import difflib
from typing import Dict, Any, List

def compute_diff(original: str, modified: str, filepath: str = "") -> Dict[str, Any]:
    """Computes unified diff stats and returns data for Monaco Diff Editor."""
    orig_lines = original.splitlines(keepends=True)
    mod_lines = modified.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        orig_lines,
        mod_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
        lineterm=""
    ))

    additions = 0
    deletions = 0
    hunks = []
    current_hunk: List[str] = []

    for line in diff:
        if line.startswith("@@"):
            if current_hunk:
                hunks.append("\n".join(current_hunk))
                current_hunk = []
            current_hunk.append(line)
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
            if current_hunk:
                current_hunk.append(line)
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
            if current_hunk:
                current_hunk.append(line)
        elif current_hunk:
            current_hunk.append(line)

    if current_hunk:
        hunks.append("\n".join(current_hunk))

    return {
        "filepath": filepath,
        "additions": additions,
        "deletions": deletions,
        "total_changes": additions + deletions,
        "unified_diff": "\n".join(diff),
        "hunks": hunks,
        "original": original,
        "modified": modified
    }
