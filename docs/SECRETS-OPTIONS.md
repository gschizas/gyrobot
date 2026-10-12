# Secrets storage: options considered

Context: the bot's secrets are env files in `.env.d/`, `config/*.credentials.yml` (Kubernetes tokens), DB DSNs, the
GitHub App key and PAT, the LDAP bind password, and the Reddit and Slack tokens. The server runs Linux, so there is
no DPAPI. The option currently preferred, systemd credentials, is described in `SYSTEMD-CREDENTIALS.md` (parked
until the server has systemd 250+). See also `TODO.md`, "Secrets storage".

## Limits common to every option

DPAPI protects a secret from other users and from stolen disk images, not from the process that uses it. The same
is true on Linux: nothing here stops someone who can run code as the bot's own user.

## Options

**1. Tight file permissions (baseline)**
- Pros: no new software. `chmod 600`, a dedicated service user, and keeping secrets out of git and Docker images.
  The biggest win for the least effort.
- Cons: still plaintext on disk, so backups, disk snapshots and anyone with root can read it.

**2. systemd credentials (`LoadCredential=`, `systemd-creds encrypt`)** (see `SYSTEMD-CREDENTIALS.md`)
- Pros: closest to DPAPI. Encrypted at rest, bound to the machine's TPM2 and/or host key, decrypted into a private
  in-memory directory only for the service. No extra server.
- Cons: needs systemd 250+ (Ubuntu 22.04 has 249), ideally a TPM. Fits Docker poorly. Moving the VM breaks
  decryption. The bot must read credentials from files instead of env vars.

**3. Docker/Compose secrets (`/run/secrets/...`)**
- Pros: mounted as tmpfs files, kept out of the image and `docker inspect`. Fits the `run.sh` setup with small
  changes.
- Cons: with plain Compose the source is still a plaintext file on the host. Real encryption needs Swarm or
  Kubernetes.

**4. Kubernetes/OpenShift Secrets (if the bot runs there)**
- Pros: native, RBAC-controlled, can be combined with etcd encryption or an external secrets operator.
- Cons: base64 is not encryption without etcd encryption; means redesigning how the bot is deployed.

**5. Encrypting at rest with your own key (Fernet / age / SOPS)**
- Pros: secrets can be committed or backed up safely. SOPS encrypts individual fields of YAML, which suits the
  `*.credentials.yml` files, and can use age keys or cloud KMS.
- Cons: the key still has to live somewhere, so this moves the problem unless the key comes from systemd
  credentials, a TPM or a KMS. Adds a decrypt step at startup and key-rotation work.

**6. OS keyring / Secret Service (`keyring`, gnome-keyring, KWallet)**
- Pros: encrypted store with a standard Python API.
- Cons: designed for desktop sessions. On a headless server it needs a D-Bus session and an unlocked keyring, which
  is fragile for a daemon. Not recommended.

**7. HashiCorp Vault / OpenBao**
- Pros: the most complete option: central audit logs, rotation, dynamic short-lived credentials (for example for
  the DB), fine-grained policies.
- Cons: a service to run, unseal and back up; the bot also needs its own credential to reach Vault. Overkill for one
  bot unless the organisation already runs Vault.

**8. Cloud secret managers (Azure Key Vault, AWS or GCP Secrets Manager)**
- Pros: managed and audited, with managed identities that avoid a bootstrap secret. Azure Key Vault would fit well
  if already on AKS.
- Cons: needs cloud connectivity and an identity; adds latency and a dependency. Only sensible if the server is
  already in that cloud.

**9. Hardware or file-based key protection (TPM, HSM, YubiHSM)**
- Pros: the key cannot be copied off the machine.
- Cons: complex and tied to specific hardware; usually unjustified for a bot.

## Azure Key Vault

Details, authentication options and questions for the Azure admins are in `AZURE-KEY-VAULT.md`.

## Recommendation

- **Now:** option 1 (tight permissions), plus option 2 under systemd once the OS allows it, or option 3 under Docker.
- **If the organisation already runs Vault or Azure Key Vault:** use that instead, and add rotation for the GitHub
  App key.
- **Fewer long-lived secrets:** prefer short-lived tokens where possible, such as the GitHub App installation
  tokens already in use. The long-lived PAT (`ses_usr`) is the riskiest secret; replace it with an App token where
  GitHub allows.
- **Code change that helps every option:** read each secret from `$NAME` or `$NAME_FILE` (a path), so the backend
  can change later without touching the code.
