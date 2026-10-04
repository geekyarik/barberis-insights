"""Scheduler: run jobs on a cadence, catching up on slots missed while the laptop was asleep. Use `jobs.service`."""


def _discover() -> None:
    import importlib
    import pkgutil
    for m in pkgutil.iter_modules(__path__):
        if not m.name.startswith("_") and m.name not in {"registry", "service"}:
            importlib.import_module(f"{__name__}.{m.name}")
