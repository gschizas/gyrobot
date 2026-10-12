# Azure Key Vault for the bot's secrets

Part of the secrets-storage evaluation; see `SECRETS-OPTIONS.md` for the other options and `TODO.md`, "Secrets
storage". Status: exploring, nothing implemented.

Stores secrets (any string up to 25 KB), keys and certificates; for the bot only secrets matter.

- **Authentication:** Microsoft Entra ID; there is no vault password. **Authorization:** use Azure RBAC; the role
  "Key Vault Secrets User" gives read-only access, scoped to a vault or a single secret. (Access policies are
  legacy.)
- **Features:** secret versioning; soft delete (7-90 days) and purge protection; audit logs via Azure Monitor (which
  identity read which secret, when); firewall and private endpoints; Event Grid events (for example, secret near
  expiry). Secrets are not rotated automatically; rotation has to be scripted (for example an Azure Function).
- **Cost:** very low, billed per 10,000 operations (a few cents); check the current price list. Standard vs Premium
  only matters for HSM-backed keys.
- **Python:** `azure-identity` + `azure-keyvault-secrets`:
  ```python
  from azure.identity import DefaultAzureCredential
  from azure.keyvault.secrets import SecretClient

  client = SecretClient("https://<vault>.vault.azure.net", DefaultAzureCredential())
  token = client.get_secret("github-token").value
  ```
- **Kubernetes:** on AKS, the Secrets Store CSI Driver (Azure provider) mounts vault secrets as files using workload
  identity; no secret lives in the cluster.
- **Cons to plan for:** the bot must reach the vault at startup (fetch once and cache in memory, so a short outage
  does not break a running bot); the vault throttles requests (never fetch per call); a tenant admin must create the
  vault and grant roles; adds an Azure SDK dependency.

## How the bot would authenticate (the bootstrap problem)

The bot needs an identity to reach the vault. Options, from best to simplest:

1. **Managed identity** (no stored secret):
   - If the VM runs in Azure: enable a system-assigned managed identity.
   - If the VM is on-prem or elsewhere: **Azure Arc** is a lightweight agent (`azcmagent`) that registers the server
     in Azure and gives it a managed identity. Worthwhile only if the Azure admins already use Arc for on-prem
     servers; otherwise it needs the agent, outbound HTTPS to Azure endpoints and an admin to approve the
     registration, which is a lot for a single bot.
2. **Service principal with a certificate** (works today, also on Ubuntu 22.04, no Arc needed): the admins create an
   app registration; a certificate is created for it and its private key kept in a root-owned file; the bot
   authenticates with `CertificateCredential`. Only the certificate sits on disk, and it can be revoked in Entra
   without exposing the vault. Less secure than a managed identity (anyone who can read the key file can use it),
   but still gives central audit, versioning and rotation.
3. **Service principal with a client secret:** simplest, but a long-lived secret on disk, which defeats most of the
   benefit. Avoid.

## Questions for the Azure admins

1. Do we already use Azure Arc for on-prem servers?
2. Can we get a Key Vault (or a shared one) for the bot, with "Key Vault Secrets User" for the bot's identity?
3. If Arc is not in use, can they create an app registration and certificate for the bot?

## Possible path

1. Write a `get_secret(name)` helper that tries `$NAME`, then `$NAME_FILE`, then Key Vault, and caches the value.
2. Start with the service-principal certificate.
3. Later switch to a managed identity (Azure VM or Arc) without changing the rest of the code.
