# Repository summary prompt contract

The repository reducer receives compact structured evidence from file analyses and returns:

- purpose and functionality,
- frameworks and libraries,
- architecture style and layers,
- patterns and data flow,
- noteworthy aspects,
- explicit assumptions and limitations.

The evidence is token-truncated only after individual file analyses have been preserved in the final JSON artifact.
