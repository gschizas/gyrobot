from typing import Optional

from backend.secret_store.base import SecretBackend, SecretBackendError, check_name, register_backend


@register_backend
class AzureKeyVaultBackend(SecretBackend):
    """Azure Key Vault secrets. Needs ``pip install azure-identity azure-keyvault-secrets``.

    ``vault_url``: ``https://<vault>.vault.azure.net``.
    ``auth``: ``default`` (``DefaultAzureCredential``: managed identity, environment, az login, ...) or
    ``certificate`` (service principal; needs ``tenant_id``, ``client_id`` and ``certificate_path``, a PEM or PFX file).
    Key Vault names allow only letters, digits and hyphens, so ``_`` in the secret name is mapped to ``-``.
    """
    type_name = 'azure_keyvault'

    def __init__(self, vault_url: str, auth: str = 'default', tenant_id: Optional[str] = None,
                 client_id: Optional[str] = None, certificate_path: Optional[str] = None):
        if auth not in ('default', 'certificate'):
            raise ValueError(f"auth must be 'default' or 'certificate', not {auth!r}")
        if auth == 'certificate' and not (tenant_id and client_id and certificate_path):
            raise ValueError("auth 'certificate' needs tenant_id, client_id and certificate_path")
        self.vault_url = vault_url
        self.auth = auth
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.certificate_path = certificate_path
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from azure.keyvault.secrets import SecretClient
                from azure.identity import CertificateCredential, DefaultAzureCredential
            except ImportError as e:
                raise SecretBackendError(
                    "Azure packages not installed (pip install azure-identity azure-keyvault-secrets)") from e
            if self.auth == 'certificate':
                credential = CertificateCredential(self.tenant_id, self.client_id,
                                                   certificate_path=self.certificate_path)
            else:
                credential = DefaultAzureCredential()
            self._client = SecretClient(self.vault_url, credential)
        return self._client

    def get(self, name: str) -> Optional[str]:
        check_name(name)
        client = self._get_client()
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return client.get_secret(name.replace('_', '-')).value
        except ResourceNotFoundError:
            return None
        except Exception as e:
            raise SecretBackendError(f"Key Vault lookup of {name} failed: {e}") from e

    def describe(self) -> str:
        return f"{self.type_name} ({self.vault_url})"
