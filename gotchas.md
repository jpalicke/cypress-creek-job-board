# Gotchas

Strict rules added after corrections. Format: the rule, then why.

## Git identity is the noreply address
Never commit with the personal gmail address. The repo identity is user.name "jpalicke" and user.email "13882087+jpalicke@users.noreply.github.com". Check `git config user.email` before the first commit in any clone.
Why: the first commit carried the personal address, which is public in a public repo and attracts spam. It had to be amended and force pushed.
