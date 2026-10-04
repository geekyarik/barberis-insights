"""Analyses: one module per analysis, a stored run per result. Use `analyses.service`; do not import analysis modules directly."""


def _discover() -> None:
    import importlib
    import pkgutil
    for m in pkgutil.iter_modules(__path__):
        if not m.name.startswith("_") and m.name not in {"base", "registry", "compare", "service"}:
            importlib.import_module(f"{__name__}.{m.name}")
