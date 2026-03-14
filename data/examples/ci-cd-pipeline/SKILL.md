---
name: "ci-cd-pipeline"
description: "Set up a reliable CI/CD pipeline that automates testing, building, and deployment"
tags: ["devops", "ci-cd", "automation", "github-actions", "deployment"]
---

## Instructions

A CI/CD pipeline automates the path from a developer's commit to a running production deployment, catching errors early and reducing manual toil.

**Pipeline Stages (in order)**
1. **Lint & Format Check**: Fast, zero-dependency checks that give developers immediate feedback. Fail fast here — if the code does not even parse, skip later stages.
2. **Unit Tests**: Run the full unit test suite. This should complete in under 5 minutes.
3. **Build Artifact**: Compile, bundle, or build the Docker image. Tag images with the git SHA for traceability.
4. **Integration Tests**: Spin up dependencies via Docker Compose and run integration/e2e tests against the built artifact.
5. **Security Scan**: Run a dependency vulnerability scan (e.g., `trivy`, `snyk`, `npm audit`) and a static analysis tool. Gate on critical severity findings.
6. **Publish Artifact**: Push the Docker image to the container registry or upload the build artifact to object storage.
7. **Deploy to Staging**: Automatically deploy every merged commit to a staging environment.
8. **Deploy to Production**: Deploy on a manual approval trigger (or automatically on tags) using a blue-green or canary strategy.

**GitHub Actions Example Structure**
```yaml
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: npm ci
      - run: npm test
```

**Best Practices**
- Cache dependency layers (`actions/cache`, `--mount=type=cache` in Docker) to keep pipelines fast.
- Store all secrets in the CI secret store — never in the repository.
- Make every pipeline step idempotent so re-runs are safe.
- Set timeouts on each job to prevent runaway builds from consuming quota.
- Notify the team on failure via Slack or email; silence is not an acceptable failure mode.
