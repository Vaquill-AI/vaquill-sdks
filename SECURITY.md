# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately. Do not open a public issue or pull request.

1. Preferred: use GitHub private vulnerability reporting at https://github.com/Vaquill-AI/vaquill-sdks/security/advisories/new (the Security tab of this repository, "Report a vulnerability").
2. Fallback: email contact@vaquill.ai with "Security" in the subject.

Include the package, its version, a description of the impact and the smallest reproduction you can.
Never include a live API key. If a key may have leaked, rotate it in the Vaquill developer console first.

We aim to acknowledge a report within 3 business days.
After triage we will tell you whether we accept it and keep you updated until it is resolved.
We publish a GitHub security advisory for every confirmed vulnerability and credit the reporter unless asked not to.

## Supported versions

While the packages are on 0.x, only the latest released 0.x version of each package (`vaquill` on PyPI and `@vaquill-ai/sdk` on npm) receives security fixes.
Older versions are not patched, so upgrade to the latest release.
After 1.0 this policy will be revised and published here.

## Scope

In scope: the SDKs in this repository (`vaquill` on PyPI and `@vaquill-ai/sdk` on npm), their release pipelines and their published packages.
Out of scope: the Vaquill API service itself. Report API issues through the same channel and we will route them.

## Release integrity

Releases are built in GitHub Actions from a tagged commit and published through a protected environment, with no long-lived publish credentials where the registry supports it.
Third-party actions are pinned by commit SHA.
