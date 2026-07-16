# Submission checklist

- [ ] Replace the placeholder author/name in `pyproject.toml` if needed.
- [ ] Create a private or public Git repository and commit all files except `.env` and `.analysis-cache`.
- [ ] Run `python -m pip install -e ".[dev]"`.
- [ ] Run `pytest` and `ruff check src tests`.
- [ ] Copy `.env.example` to `.env` and set a valid API key.
- [ ] Run the target repository in **LLM mode** (without `--offline`).
- [ ] Run `codebase-analyzer validate-output output/analysis.json`.
- [ ] Review the generated descriptions for provider/model-specific mistakes.
- [ ] Push the final commit and verify the Git link in an incognito browser.
- [ ] Reply-all to the invitation email with the repository link.

Suggested email:

> Hi Reshma and Balaji,  
> Thank you for the assignment. I have completed the codebase-analysis solution and uploaded it here: **[Git repository link]**. The repository includes the implementation, structured JSON output, tests, setup instructions, design decisions, assumptions, and limitations. I look forward to walking through the solution during the screen-sharing session.  
> Best regards,  
> Daniel
