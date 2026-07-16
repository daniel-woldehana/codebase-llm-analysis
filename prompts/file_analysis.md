# File analysis prompt contract

The production prompt is defined in `src/codebase_analyzer/prompts.py` so it can be versioned and tested with the application. It instructs the LLM to:

1. Stay grounded in source code and deterministic parser facts.
2. Describe only classes and methods that exist.
3. Return a strict Pydantic-compatible JSON object.
4. Identify concrete dependencies, risks, and noteworthy implementation details.
5. Avoid generic advice and unsupported claims.
