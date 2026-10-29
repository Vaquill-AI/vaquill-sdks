# Releasing the Kotlin SDK

Releases go to Maven Central as `ai.vaquill:vaquill-kotlin`.
A release is a pushed tag named `kotlin-vX.Y.Z` (or `kotlin-vX.Y.Z-rc.1` for a pre-release).
The workflow `.github/workflows/kotlin-release.yml` then runs the full Kotlin CI, builds, waits for a reviewer to approve the `maven-central` environment, signs, uploads to the Sonatype Central Portal and creates a GitHub Release.

Maven Central is immutable.
A published version can never be changed or removed, so fix a bad release with the next version number.

Nothing in this file has been executed against the real Central Portal.
The steps below follow Sonatype's documentation; correct this file if the Portal UI has moved.

## One-time setup (owner only)

### 1. Sonatype Central Portal account and namespace

1. Go to https://central.sonatype.com and choose Sign In, then create an account (GitHub or Google login is fine).
2. Open https://central.sonatype.com/publishing/namespaces and choose Add Namespace.
3. Enter `ai.vaquill` and submit. The Portal shows a verification key (a random string).
4. Prove ownership of the domain `vaquill.ai`: add a DNS TXT record on `vaquill.ai` whose value is exactly that verification key. (The `ai.vaquill` namespace is the reversed domain `vaquill.ai`.)
5. Back on the Namespaces page choose Verify Namespace. Wait until the status is Verified. DNS can take minutes to propagate.

### 2. Publisher token

1. At https://central.sonatype.com/account choose Generate User Token.
2. Copy the two values it shows (a username and a password). They are shown once.
3. These are the secrets `ORG_GRADLE_PROJECT_centralUsername` and `ORG_GRADLE_PROJECT_centralPassword` below.
   They are not your Portal login.

### 3. GPG signing key

Central rejects unsigned artifacts. Create a dedicated key for releases:

```bash
gpg --full-generate-key
#   kind: RSA and RSA, size 4096
#   validity: 2y (set a calendar reminder to rotate it)
#   name: Vaquill Releases, email: an address you control
#   set a strong passphrase
gpg --list-secret-keys --keyid-format long      # note the key id after "rsa4096/"
```

Publish the public key so Central can verify signatures (Central checks these key servers):

```bash
gpg --keyserver keyserver.ubuntu.com --send-keys <KEYID>
gpg --keyserver keys.openpgp.org --send-keys <KEYID>
```

For keys.openpgp.org, open the confirmation email it sends and click the link, otherwise the key has no user id there.

Export the private key as ASCII armor for the secret:

```bash
gpg --armor --export-secret-keys <KEYID> | pbcopy      # macOS; paste into the secret, then clear the clipboard
```

Keep an offline backup of the private key and the passphrase (a password manager). If you lose them you can still release with a new key, but you cannot reuse the old one.

### 4. GitHub environment

In the repository (vaquill-ai/vaquill-sdks): Settings, Environments, New environment, name it exactly `maven-central`.

1. Tick Required reviewers and add yourself (and one more person if you have one).
   Tick Prevent self-review only if a second reviewer exists, otherwise the release can never be approved.
2. Under Deployment branches and tags choose Selected branches and tags, then add a tag rule `kotlin-v*`.
3. Under Environment secrets add exactly these four names:

| Secret | Value |
| --- | --- |
| `ORG_GRADLE_PROJECT_signingInMemoryKey` | the ASCII-armored private key from step 3, including the BEGIN and END lines |
| `ORG_GRADLE_PROJECT_signingInMemoryKeyPassword` | the key passphrase |
| `ORG_GRADLE_PROJECT_centralUsername` | the token username from step 2 |
| `ORG_GRADLE_PROJECT_centralPassword` | the token password from step 2 |

Use environment secrets, not repository secrets, so only an approved run of this workflow can read them.

### 5. Repository protections (recommended)

Settings, Rules, Rulesets: protect tags matching `kotlin-v*` so only maintainers can create them, and require reviews on the default branch.
The workflow refuses a tag whose commit is not on the default branch.

## Cutting a release

1. Set `version = "X.Y.Z"` in `kotlin/build.gradle.kts` and update the version in `kotlin/README.md` (Install and Coordinates).
2. Merge that to the default branch and wait for Kotlin CI to pass.
3. For the first release, or after any change to the workflow or signing, tag a pre-release first:
   `version = "0.1.0-rc.1"`, tag `kotlin-v0.1.0-rc.1`. The tag must equal the Gradle version or the workflow stops.
4. Push the tag:

   ```bash
   git tag kotlin-v0.1.0
   git push origin kotlin-v0.1.0
   ```

5. Open the run in the Actions tab. After the checks and the build job pass, the `publish` job waits for approval. Review and approve the `maven-central` deployment.
6. The workflow uploads the signed artifacts, then hands them to the Portal with `publishing_type=automatic`, which releases them as soon as validation passes.
   To keep a final manual gate, change that to `user_managed` in the workflow; the deployment then waits in https://central.sonatype.com/publishing/deployments until you press Publish.
7. Watch https://central.sonatype.com/publishing/deployments. A deployment ends Published or Failed with the failing rule named (missing signature, missing POM field, unverified namespace).
   The artifact appears on https://repo1.maven.org/maven2/ai/vaquill/vaquill-kotlin/ after a short delay (usually within 30 minutes, search indexing can take hours).
8. The `github-release` job then creates the GitHub Release with the jars attached.

## If something fails

* `Secret ... is empty`: the environment secret is missing or misspelled.
* `401` or `403` on upload: wrong token, or the namespace `ai.vaquill` is not Verified yet.
* Deployment Failed in the Portal with a signature error: the public key is not on a key server Central reads, or the key expired.
* The workflow failed after the upload step: the staged repository may still exist. Check the Portal deployments page before re-running, because a re-run would try to upload the same version.
* Remember that a version the Portal marked Published can never be re-published.
