$ErrorActionPreference = "Stop"
python -m pip install -e ".[dev]"
codebase-analyzer analyze `
  --repo "https://github.com/codejsha/spring-rest-sakila.git" `
  --output "output/analysis.json"
