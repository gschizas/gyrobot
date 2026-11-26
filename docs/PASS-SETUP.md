# Setting up `pass` for the bot's passwords

Runbook for the `pass` backend of the secret store (`SECRET-STORE.md`). Chosen because keyring needs a desktop
session and systemd credentials need systemd 250+ (see `SECRETS-OPTIONS.md`). The secrets are GPG-encrypted at rest
under a passphrase-protected key; after each reboot someone unlocks the key once.

Secrets for the Crowd onboarding:

| Secret name | Used for |
|---|---|
| `CROWD_PASSWORD` | The Crowd application password (Crowd itself does not talk to LDAP). |
| `LDAP_BIND_PASSWORD` | The read-only AD service account that only looks up emails and display names. |
| `BITBUCKET_TOKEN` | Optional Bitbucket access token (project and repository admin, read use only) for the repository list in the email. |

The matching user names are not secret: put `CROWD_USERNAME` and `LDAP_BIND_USERNAME` in the instance env file
(`.env.d/<name>.env`) as plain values. (If you would rather keep them out of the file, `CROWD_USERNAME=secret:` works
too, since any name can be looked up in the store.)

Use a dedicated AD account that can only bind and search, with a long random password.

## 1. Install (as root)

```sh
apt install pass gnupg pinentry-curses
```

Run everything below as the user the bot runs as (the key and the agent belong to that user).

## 2. Create the key (once)

```sh
export GPG_TTY=$(tty)
gpg --quick-generate-key "GyroBot <gyrobot@localhost>" rsa3072 encrypt never
```

Choose a strong passphrase when asked (do not leave it empty: an empty passphrase is no better than a plain file).
Note the fingerprint: `gpg --list-secret-keys --keyid-format long`.

## 3. Let the agent remember the passphrase

`~/.gnupg/gpg-agent.conf`:

```
pinentry-program /usr/bin/pinentry-curses
default-cache-ttl 604800
max-cache-ttl 604800
```

(seconds; a week. The agent only keeps the passphrase in memory, so it is forgotten at reboot.) Then
`gpgconf --kill gpg-agent`.

## 4. Create the store and add the secrets

```sh
pass init <fingerprint>
pass insert <env-name>/CROWD_PASSWORD
pass insert <env-name>/LDAP_BIND_PASSWORD
```

One folder per environment (`<env-name>` is the name of the `.env.d/<env-name>.env` file), so each instance has its
own passwords.

Keep a copy of the passwords (and an export of the key, `gpg --export-secret-keys --armor`) in your password manager:
the store cannot be rebuilt without the key and passphrase.

## 5. Point the bot at it

The `prefix` in `secrets.yml` is a fixed string, so use one file per environment, `config/secrets.<env-name>.yml`,
and select it with `SECRETS_CONFIGURATION=secrets.<env-name>.yml` in the process environment (it cannot come from the
`.env.d` file itself, which is read through the store):

```yaml
backends:
  - type: pass
    prefix: <env-name>
    first_line_only: true
```

If the bot runs as a different user or home than the key, add `gnupghome: /path/.gnupg` (and `store_dir`).
In code, `get_secret('CROWD_PASSWORD', required=True)`; in an `.env.d` file, `CROWD_PASSWORD=secret:`.

## 6. After every reboot

Unlock the key once, as the bot's user, before starting the bot:

```sh
export GPG_TTY=$(tty)
pass show <env-name>/CROWD_PASSWORD > /dev/null
```

It asks for the passphrase and the agent then answers the bot without prompting, until the TTL ends. The backend runs
`pass` with stdin closed, so a locked agent makes the lookup fail fast with a message instead of hanging; the bot
logs it as a backend warning.

## Docker

The bot's container does not see the host's agent. Either install `pass` and `gnupg` in the image and mount the
agent socket (`gpgconf --list-dirs agent-socket`) and the store read-only, or resolve the secrets outside the
container and pass them in as files (the `directory` backend with `path: /run/secrets`). Not tried yet.

## Limits

This protects against stolen disks, snapshots and backups, and other users. It does not protect against root, or
against anyone who can run code as the bot's user while the agent is unlocked.
