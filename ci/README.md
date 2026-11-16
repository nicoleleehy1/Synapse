# CI workflow

`github-actions.yml` is the GitHub Actions pipeline for this repo. It runs backend lint and tests against a Neo4j service container, the frontend lint, typecheck, tests and build, and builds both Docker images.

It lives here only because the tool that opened this pull request can't write to `.github/workflows/`. To turn it on, move it to `.github/workflows/ci.yml` (on GitHub: open the file, click the pencil, and change the path) and delete this folder.
