"""Comparison of two analysis runs: what moved, whether it is better or worse, and what findings appeared or resolved."""
from __future__ import annotations


def not_comparable(before, after) -> list[str]:
    """Reasons two runs cannot be compared (empty when they can). Both are AnalysisRun rows."""
    why = []
    if before.analysis_key != after.analysis_key:
        why.append("different analyses")
    if before.analysis_version != after.analysis_version:
        why.append(f"analysis version differs ({before.analysis_version} vs {after.analysis_version})")
    if before.scope != after.scope:
        why.append(f"scope differs ({before.scope} vs {after.scope})")
    if (before.lens, before.lens_resolved) != (after.lens, after.lens_resolved):
        why.append("lens differs (or resolved to different factors)")
    if before.params != after.params:
        why.append("parameters differ")
    changed = sorted(k for k in set(before.metric_versions) | set(after.metric_versions) if before.metric_versions.get(k) != after.metric_versions.get(k))
    if changed:
        why.append("metric definitions differ: " + ", ".join(changed))
    if (before.window_to - before.window_from) != (after.window_to - after.window_from):
        why.append("windows have different lengths")
    if not before.result.get("complete", True) or not after.result.get("complete", True):
        why.append("a window is not fully observed yet")
    return why


def compare_runs(before, after) -> dict:
    why = not_comparable(before, after)
    out = {"before": before.id, "after": after.id, "comparable": not why, "reasons": why, "changes": {}, "findings": {"new": [], "resolved": []}}
    if why:
        return out
    directions = after.result.get("directions", {})
    b, a = before.result.get("kpis", {}), after.result.get("kpis", {})
    for scope, kpis in a.items():
        for k, new in kpis.items():
            old = b.get(scope, {}).get(k)
            if old is None or new is None:
                continue
            delta = round(new - old, 2)
            d = directions.get(k)
            verdict = "same" if delta == 0 else "unknown" if d is None else "better" if (delta > 0) == (d == "up") else "worse"
            out["changes"].setdefault(scope, {})[k] = {"before": old, "after": new, "delta": delta, "verdict": verdict}
    ident = lambda f: (f["code"], f["scope"])
    old_f, new_f = {ident(f): f for f in before.result.get("findings", [])}, {ident(f): f for f in after.result.get("findings", [])}
    out["findings"]["new"] = [f for i, f in new_f.items() if i not in old_f]
    out["findings"]["resolved"] = [f for i, f in old_f.items() if i not in new_f]
    return out
