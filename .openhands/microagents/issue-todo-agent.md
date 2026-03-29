---
name: Issue Todo Agent
type: knowledge
version: 1.0.0
agent: CodeActAgent
triggers:
  - issue
  - TODO
---

# Issue Todo Agent

This microagent is triggered when working on issues raised in the repository.

## Capabilities

- Analyze issues and TODOs in the codebase
- Fix bugs and implement improvements
- Create appropriate test cases
- Commit changes with descriptive messages
- Push changes to the repository

## Workflow

1. When triggered by "issue" or "TODO", analyze the repository to understand the context
2. Look for existing issues in the GitHub repository
3. Identify the problem and implement a fix
4. Ensure the code is properly tested
5. Commit changes with clear, descriptive messages
6. Push to a new branch and create a pull request

## Limitations

- Requires GitHub token for pushing changes
- Should not push directly to main/master branches
- Must follow repository's pull request template when available
