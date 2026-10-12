# Protecting secrets with systemd credentials (future work)

Status: **not implemented**. Needs systemd 250 or newer for the encrypted part; Ubuntu 22.04 ships 249, so this is
parked until the server is upgraded to Ubuntu 24.04 LTS (systemd 255) or later. See `TODO.md`, "Secrets storage".

## What the server supports

| Feature | Needs | Ubuntu 22.04 (systemd 249) |
|---|---|---|
| `LoadCredential=` (plain file delivered to the service) | v247 | Works |
| `systemd-creds`, `LoadCredentialEncrypted=` (encrypted at rest) | v250 | Not available |
| `SetCredentialEncrypted=`, TPM2 sealing | v250+ | Not available |

Do not upgrade systemd by hand on 22.04; it is too tightly tied to the OS.

## What it protects (and what it does not)

Protects secrets on disk (backups, snapshots, other local users). It does not protect against root on the box, or
anyone who can run code as the bot's own user.

## Upgrade checklist

- Snapshot/back up the VM first.
- `sudo do-release-upgrade` (24.04 LTS). Ubuntu 22.04 is supported until 2027.
- Afterwards check that Python, `uv`, the Postgres client and the `gyrobot@` / `gyrobot-web@` services still start.

## Setup steps (on systemd 250+)

1. Check the version: `systemctl --version` (should be 255 or newer).
2. Check for a TPM: `systemd-creds has-tpm2` (see below). Without a TPM the key lives on the root filesystem, so a
   stolen disk image would expose it; the secrets are then protected only against other users and casual copies.
3. Create the host key: `sudo systemd-creds setup`.
4. Encrypt each secret. The `--name` must match the name used in the unit:
   ```sh
   sudo mkdir -p /etc/gyrobot/creds
   sudo systemd-creds encrypt --name=github_token - /etc/gyrobot/creds/github_token.cred
   # paste the value, then press Ctrl-D
   sudo chmod 600 /etc/gyrobot/creds/github_token.cred
   ```
   To seal to the TPM as well: add `--with-key=host+tpm2`.
5. Add the credential to the unit with a drop-in per instance (`sudo systemctl edit gyrobot@prod`):
   ```ini
   [Service]
   LoadCredentialEncrypted=github_token:/etc/gyrobot/creds/github_token.cred
   ```
6. The service gets `$CREDENTIALS_DIRECTORY`; the secret is the file `$CREDENTIALS_DIRECTORY/github_token`.
7. `sudo systemctl daemon-reload && sudo systemctl restart gyrobot@prod`.

## Things to know

- Credentials are bound to the machine (and TPM). They will not decrypt on another host, so keep the plain
  secrets in a password manager to rebuild.
- Code change needed: a small helper that reads a secret from the environment variable first, then from
  `$CREDENTIALS_DIRECTORY/<name>`. Secrets can then be migrated one at a time.
- On 22.04, `LoadCredential=` (plain, root-owned files outside the bot directory) can already be used to
  write and test the code path, but gives no encryption at rest.

## Testing whether the VM has a TPM

Run these on the server (a TPM 2.0 is needed; a vTPM must be enabled on the hypervisor):

```sh
ls /dev/tpm0 /dev/tpmrm0                    # both should exist
sudo dmesg | grep -i tpm                    # kernel messages about the TPM
cat /sys/class/tpm/tpm0/tpm_version_major   # should print 2
systemd-creds has-tpm2                      # (systemd 250+) reports whether TPM2 is usable
```

If nothing exists, the VM has no TPM. Depending on the hypervisor, enable it as follows (the VM usually has to be
powered off, and needs UEFI firmware rather than legacy BIOS):

- **Hyper-V:** Generation 2 VM, Settings > Security > Enable Trusted Platform Module.
- **VMware vSphere:** add a "Virtual Trusted Platform Module" device (needs UEFI firmware and encryption support).
- **Proxmox/KVM:** add a TPM State disk (TPM v2.0) to the VM.
- **Cloud (Azure, AWS, GCP):** use a trusted-launch / vTPM-enabled instance type.
