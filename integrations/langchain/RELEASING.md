# Releasing langchain-vaquill

Publishing is a tag push.
Nothing is uploaded from a laptop and no PyPI token is stored anywhere.
The workflow is `.github/workflows/integration-langchain-release.yml` in the repository root, and it authenticates to PyPI with Trusted Publishing (OIDC).

## One-time setup (repository owner only)

Do these once, before the first tag.
A first release of a project that does not exist on PyPI yet uses a pending publisher, which creates the project on the first successful publish.

### 1. GitHub environment

1. Open the repository on GitHub, then Settings, then Environments, then New environment.
2. Name it exactly `pypi-langchain`.
3. Tick Required reviewers and add the person who approves a release.
4. Under Deployment branches and tags, choose Selected branches and tags, then add a tag rule `langchain-vaquill-v*`.
5. Add no secrets and no variables. Trusted Publishing needs none.

### 2. PyPI pending publisher

1. Sign in at https://pypi.org with the account that will own the project.
2. Open Your account, then Publishing (https://pypi.org/manage/account/publishing/).
3. Under Add a new pending publisher, choose the GitHub tab.
4. Fill the form with exactly these values.

| Field | Value |
| --- | --- |
| PyPI Project Name | `langchain-vaquill` |
| Owner | `Vaquill-AI` |
| Repository name | `vaquill-sdks` |
| Workflow name | `integration-langchain-release.yml` |
| Environment name | `pypi-langchain` |

5. Click Add.
Before this step, check that https://pypi.org/project/langchain-vaquill/ does not already belong to someone else.
If the name is taken the first publish fails and you must pick another name in `pyproject.toml`.

### 3. Protect the tags (recommended)

1. Settings, then Rules, then Rulesets, then New tag ruleset.
2. Target the pattern `langchain-vaquill-v*`.
3. Restrict creations and block updates and deletions.

## Cutting a release

1. Change `__version__` in `src/langchain_vaquill/_version.py` (the only place the version lives).
2. Open a pull request, let `Integration LangChain CI` pass, and merge it to the default branch.
3. Tag the merge commit and push the tag: `git tag langchain-vaquill-vX.Y.Z && git push origin langchain-vaquill-vX.Y.Z`.
4. Pre-releases use PEP 440 suffixes: `langchain-vaquill-vX.Y.ZrcN` (also `aN`, `bN`).
5. The workflow runs the full package CI on the tag, builds the sdist and wheel, runs `twine check --strict`, installs the wheel in a clean environment and imports it.
6. The publish job then waits for a reviewer on the `pypi-langchain` environment. Approve it in the Actions run.
7. After PyPI accepts the files, a GitHub Release with generated notes and the built files is created.

The workflow refuses a tag that does not equal `__version__` or whose commit is not on the default branch.
A version that reached PyPI can never be re-uploaded, so a failed release after the publish step needs a new version number.

## After the first publish

Once the project exists on PyPI, the pending publisher turns into an ordinary trusted publisher with the same values.
Nothing else needs to change.
