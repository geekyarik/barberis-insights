# Analyses are code; their results are stored runs that we compare over time

The first business analyses were done by hand in chat and published as one-off pages, which could not be repeated, compared or trusted later. Instead, every metric and every analysis is its own versioned module with a pure `run` (and `compare` for analyses), and each execution is stored as an immutable analysis run with its window, scope, lens, versions and a fingerprint of the data. Goals are set against a baseline run, and progress is the comparison of later runs with it. Claude may write narrative on top of stored runs but never replaces them. This costs more structure up front (a module and a test per metric and analysis) in exchange for repeatable, comparable results.

## Consequences
- Changing a definition means raising its version; runs with different versions are reported as not comparable rather than silently compared.
- Reports (barber book, team comparison, monthly review) are compositions of stored runs, so a report from any past month can be rebuilt exactly.
