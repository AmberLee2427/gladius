# TODO

- [ ] Set up issue-to-PR automation, once there is an issue worth solving.
  - Trigger only when the maintainer applies a label or mentions the agent, never on every new issue.
  - Options: Copilot coding agent, Claude Code GitHub Action, or Codex (Jules is being shut down).
  - Give the agent minimal permissions and only the secrets it needs.
  - Require maintainer review for changes under `.github/workflows/`.
- [ ] Add an `actions/stale` workflow to close inactive issues.
- [ ] Get project and RGES-PIT permissions for distribution.
- [ ] Beta test the package.
- [ ] Review the notebooks.
- [ ] Run a security review.
- [ ] Add a SECURITY.md (how to report vulnerabilities).
- [ ] Confirm the Codecov upload works and set a coverage target.
- [ ] Confirm the version bump and release automation works end to end (dry run).
- [ ] Check licence, citation metadata and README before first release.
- [ ] Test the 60" corrected-WCS shift limit (`CORRECTION_MAX_OFFSET_ARCSEC`) on real commissioning data, where the delivered WCS is off by up to a few arcminutes.
- [ ] Make a conda package, once we know we are allowed to distribute (after commissioning data is released).

## From the critical review (medium/low)
