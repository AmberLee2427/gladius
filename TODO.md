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
- [ ] Make a conda package, once we know we are allowed to distribute (after commissioning data is released).

## From the critical review (medium/low)
- Release `0.1.0a4` with the Bump workflow so PyPI matches the docs and notebooks (a3 lacks named runs, `gladius.inspection`, refresh/fresh controls).
- Stabilise pixel-boundary floor in `geometry()` (round-trip gives 19.9999999990).
- Check target inversion in `validate_wcs`; bind corrected-WCS files to their parent.
- Keep sub-millisecond precision in time summaries.
- Hash each parent once per run, not per `obtain()` call.
- Decide whether `no_overlap` should default to `skip` (currently `pad`: off-image targets give an all-NaN "complete" cutout).
- GUI: cancel, output inspection, failure manifest path; live log replaced every 800 ms; primary button contrast 4.34:1; focus lost on target removal.
- Clean internal paths and the unresolved `gaia_wcs_correction.py` licence note from `NOTICE.md`.
