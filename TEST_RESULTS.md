# Verification results

The packaged solution was verified in the build environment with:

```text
PYTHONPATH=src pytest -q
.....                                                                    [100%]

python -m compileall -q src tests
(no errors)

PYTHONPATH=src python -m codebase_analyzer validate-output output/analysis.json
Valid analysis report: output/analysis.json
```

The bundled JSON contains seven verified files from a partial target snapshot and is intentionally marked as an offline example. Regenerate it in LLM mode against the complete repository before submission.
