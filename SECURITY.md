# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately. Do not open a public issue or pull request.

1. Preferred: use GitHub private vulnerability reporting. Open the Security tab of this repository and choose "Report a vulnerability".
2. Fallback: contact@vaquill.ai

Include the package, its version, a description of the impact and the smallest reproduction you can.
Never include a live API key. If a key may have leaked, rotate it in the Vaquill developer console first.

We aim to acknowledge a report within 3 business days and to give a fix or mitigation plan within 14 days.
We publish a GitHub security advisory for every confirmed vulnerability and credit the reporter unless asked not to.

## Supported versions

Only the latest released minor version of each package receives security fixes while it is on 0.x.
After 1.0, for each package the latest minor of the current and previous major versions are supported.

## Scope

In scope: the SDKs in this repository (`vaquill` on PyPI and `@vaquill/sdk` on npm), their release pipelines and their published packages.
Out of scope: the Vaquill API service itself. Report API issues through the same channel and we will route them.

## Release integrity

Releases are built in GitHub Actions from a tagged commit and published through a protected environment, with no long-lived publish credentials where the registry supports it.
Third-party actions are pinned by commit SHA.
