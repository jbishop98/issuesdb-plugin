---
name: review
description: >
  Review a pull request — show open PRs or analyze a specific PR's diff, code quality, risks, and suggestions
---

# Review a Pull Request

1. If no PR number is provided in `$ARGUMENTS`, run `gh pr list` to show open PRs and stop.
2. If a PR number is provided, run `gh pr view <number> --json title,body,author,baseRefName,headRefName,state,additions,deletions,changedFiles,labels` to get PR details.
3. Run `gh pr diff <number>` to get the diff.
4. Analyze the changes and provide a thorough code review that includes:
   - Overview of what the PR does
   - Analysis of code quality and style
   - Specific suggestions for improvements
   - Any potential issues or risks

Keep your review concise but thorough. Focus on:
- Code correctness
- Following project conventions
- Performance implications
- Test coverage
- Security considerations

Format your review with clear sections and bullet points.


# synced-from: issuesdb-plugin
