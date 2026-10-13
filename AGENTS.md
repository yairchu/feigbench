# Commit conventions

- Use Conventional Commits: `<type>[optional scope]: <description>` (for example, `fix: handle certificate verification failures` or `build: update uv dependencies`).
- Include a `Co-authored-by: Name <email>` trailer for each contributing coding agent. For Codex, use `Co-authored-by: Codex <noreply@openai.com>`.
- Separate commit trailers from the message body with a blank line, and preserve existing co-author trailers when amending commits.
- Commit completed, verified work by default; leave unrelated user changes out of the commit.
- Freely amend relevant local commits to incorporate follow-up work, but always fetch and check whether a commit is reachable from any remote branch or tag before amending it. If the check fails or publication status is uncertain, create a new commit instead.
- Do not amend published commits without explicit user authorization.
