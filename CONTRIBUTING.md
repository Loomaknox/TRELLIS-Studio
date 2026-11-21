# Contributing to TRELLIS Studio

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) when participating in the project.

## Report an issue

Check the existing GitHub issues before opening a new one. Include your Studio version,
Desktop or Server edition, and the steps to reproduce the issue. Describe the expected
result and what happened. For generation or installation issues, include your Windows
version, GPU, driver, VRAM and any optional components involved.

Use a small, shareable example when a model or image is needed. Share only relevant log
excerpts with sensitive details removed. Follow the [security policy](SECURITY.md)
when reporting a vulnerability.

## Automated pull request checks

GitHub Actions runs the [lightweight checks](.github/workflows/pr-checks.yml) on pull
requests to `main`. They check public file paths and common credential patterns, text
encoding, web syntax and preview/projection behavior. They also exercise release
version handling, package integrity, optional installer recovery and Server storage
using temporary test data. The checks use Python's standard library and locked web
dependencies. They run without a GPU, Blender or model downloads.

## Propose a change

Follow the [source installation guide](INSTALLATION.md) to set up the project. Keep each
pull request focused and describe the change, how you verified it and any checks you could
not run. For visible changes, screenshots from a test library can help reviewers.

- For web changes, run `npm ci` and `npm run check` from the repository root.
- Run the relevant scripts in [`tests/`](tests/) using the Studio Python environment
  or the runtime documented in the test. Use a small fixture to reproduce a bug where possible.
- Review the files in the pull request. Keep credentials, private paths, full logs,
  configuration, databases, model weights and personal assets out of Git.
