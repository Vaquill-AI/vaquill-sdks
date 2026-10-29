# Releasing the Java SDK

Releases publish `ai.vaquill:vaquill-sdk` to Maven Central.
A Central release cannot be deleted or overwritten, so every step below must be right before the first tag.

## One-time setup (owner only)

### 1. Sonatype Central Portal account and namespace

1. Sign in at https://central.sonatype.com (GitHub login or email).
2. Open Namespaces, choose Add Namespace, enter `ai.vaquill`.
3. The Portal shows a verification key. Add a DNS TXT record on `vaquill.ai` with host `@` and the key as its value.
4. Choose Verify Namespace. Wait until the status is Verified (usually minutes, up to a day for DNS).
5. Open Account, then Generate User Token. Save the username and password halves. This token is not your login password and can be revoked.

### 2. GPG key

Run locally, once:

```bash
gpg --full-generate-key                      # RSA 4096 (or ed25519), no expiry or 2 years, uid "Vaquill <support@vaquill.ai>"
gpg --list-secret-keys --keyid-format long   # note the long key id
gpg --keyserver keyserver.ubuntu.com --send-keys <LONG_KEY_ID>
gpg --keyserver keys.openpgp.org --send-keys <LONG_KEY_ID>   # also confirm the email link it sends
gpg --armor --export-secret-keys <LONG_KEY_ID> > vaquill-release.asc
```

Central checks the signature against public keyservers, so publish the public key before the first release.
Keep `vaquill-release.asc` and the passphrase in the password manager.
Delete `vaquill-release.asc` from disk after step 4.

### 3. GitHub environment

In the `Vaquill-AI/vaquill-sdks` repository: Settings, Environments, New environment, named exactly `maven-central`.

- Required reviewers: add the owner (and at least one other person if available). Tick Prevent self-review only if a second reviewer exists.
- Deployment branches and tags: select Selected branches and tags, add the tag rule `java-v*`.
- Do not allow administrators to bypass.

### 4. Secrets on the `maven-central` environment

Add these as Environment secrets (not repository secrets), so only an approved run can read them:

| Secret | Value |
| --- | --- |
| `MAVEN_GPG_PRIVATE_KEY` | full contents of `vaquill-release.asc` (including the BEGIN and END lines) |
| `MAVEN_GPG_PASSPHRASE` | the key passphrase |
| `CENTRAL_TOKEN_USERNAME` | username half of the Portal user token |
| `CENTRAL_TOKEN_PASSWORD` | password half of the Portal user token |

Rotate the user token and the key if either is ever exposed.

## Cutting a release

1. Set `<version>` in `java/pom.xml` to `X.Y.Z` (or `X.Y.Z-rc.1`). Never a `-SNAPSHOT`.
2. Update the version shown in `java/README.md` install snippets, merge to `main`, and wait for Java CI to pass.
3. Tag the merge commit on `main` and push the tag:

   ```bash
   git tag java-vX.Y.Z
   git push origin java-vX.Y.Z
   ```

4. The workflow `Java release` runs: full Java CI, tag and `pom.xml` version check, an unsigned build of the main, sources and javadoc jars, then it pauses for a reviewer on the `maven-central` environment.
5. Approve the run. It signs, uploads to the Central Portal, publishes automatically after validation, waits until the artifact is live, then creates the GitHub Release with the jars and signatures attached.
6. Check https://central.sonatype.com/artifact/ai.vaquill/vaquill-sdk. Search indexing can lag a little behind the publish.

If validation fails, the Portal deployment is left in a failed state and nothing is published; fix the cause, bump the version if it was already published, and tag again.
A tag that does not equal the `pom.xml` version, is not on the default branch, or is a SNAPSHOT is rejected before the approval step.

## What was and was not tested before the first release

Tested locally on JDK 11 without credentials: `mvn -Prelease -Dgpg.skip=true verify` builds the main, sources and javadoc jars; signing works with a throwaway key; `help:effective-pom` shows the required Central metadata.
Not testable without the owner's credentials: the real GPG key import in CI, the Central Portal upload, namespace verification and the environment approval gate.
