# Contract · `TenantSecret` + `TenantPaymentProvider` · Phase I1.7.a

## `TenantSecret` (data model — never exposed at API boundary)
`services/secrets/models.py`

```python
class ConnectionType(str, Enum):
    API_KEY = "api_key"                 # plain provider API key
    OAUTH_STRIPE_CONNECT = "oauth_stripe_connect"
    OAUTH_TOKEN = "oauth_token"         # generic OAuth access token

class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"

class ConnectionSummary(BaseModel):
    provider_key: str
    connection_type: ConnectionType
    connected: bool
    last_4: Optional[str]
    connected_account_id_masked: Optional[str]
    last_used_at: Optional[str]
    connected_status: ConnectionStatus
    error_log_count: int
    last_error: Optional[dict]
```

Persistence: `db.tenant_secrets` (one row per `(tenant_id, provider_key)`):
```
id                       (uuid hex)
tenant_id                str
provider_key             str
connection_type          ConnectionType
encrypted_blob           bytes (base64)  ← ciphertext of the plaintext secret
iv                       bytes (base64)  ← per-record nonce
auth_tag                 bytes (base64)  ← GCM auth tag
dek_wrapped              bytes (base64)  ← DEK wrapped by KEK
last_4                   str             ← "beef" · display-only
connected_status         ConnectionStatus
connected_account_id     str | null      ← e.g. Stripe "acct_…"
error_log                list[dict]      ← capped at 20 entries
last_used_at             iso str | null
created_at               iso str
updated_at               iso str
```

### API surface (`services.secrets`)
```python
put_secret(tenant_id, provider_key, plaintext, *, connection_type,
           connected_account_id=None, db=None) -> None
get_secret(tenant_id, provider_key, *, db=None, touch=True) -> Optional[str]
remove_secret(tenant_id, provider_key, *, db=None) -> bool
list_connections(tenant_id, *, db=None) -> List[ConnectionSummary]
connection_summary(tenant_id, provider_key, *, db=None) -> Optional[ConnectionSummary]
mark_used(tenant_id, provider_key, *, db=None) -> None
log_error(tenant_id, provider_key, *, code, message, db=None) -> None
```

### Invariants (locked by test)
1. `put_secret(...)` with the same `(tenant_id, provider_key)` **rotates** — new IV, new ciphertext, `updated_at` bumped; the prior plaintext is unrecoverable.
2. `get_secret(...)` is the ONLY method that returns plaintext, and is only called from inside provider adapters.
3. `list_connections(...)` never touches the ciphertext.
4. `log_error(...)` truncates message to 400 chars; ring-buffer capped at 20 entries via Mongo `$slice: -20`.
5. `last_4(plaintext)` returns the last 4 characters of the plaintext; empty string when `len < 4`.

---

## `TenantPaymentProvider` (abstract adapter)
`services/payments/tenant_base.py`

```python
class TenantPaymentProvider(ABC):
    provider_key: ClassVar[str]

    async def create_charge(self, *, tenant_id: str, amount_cents: int, currency: str, ...) -> ChargeResult: ...
    async def refund_charge(self, *, tenant_id: str, charge_id: str, ...) -> RefundResult: ...
    async def get_charge(self, *, tenant_id: str, charge_id: str) -> ChargeResult: ...
    async def create_payment_intent(self, *, tenant_id: str, amount_cents: int, currency: str, ...) -> PaymentIntent: ...
    async def verify_webhook(self, *, payload: bytes, headers: dict[str, str]) -> WebhookEvent: ...
    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth: ...
```

### Error taxonomy
* `TenantPaymentError` — generic provider failure (rate-limit, invalid response, misconfigured platform key). Error messages MUST NOT echo the api_key or the response body verbatim.
* `TenantNotConnected` — the tenant has no stored credential AND `STRIPE_PLATFORM_FALLBACK_ENABLED=false`.
* `UnknownProvider` (from `tenant_registry.get_provider`) — no adapter registered for the given `provider_key`.

### Registry
`services/payments/tenant_registry.py`
```python
register_provider(provider_key: str, factory: Callable[[], TenantPaymentProvider]) -> None
get_provider(provider_key: str) -> TenantPaymentProvider           # raises UnknownProvider
list_provider_keys() -> list[str]
```

### Concrete implementations (I1.7.a)
* `stripe` — `services/payments/tenant_stripe.py::StripeConnectProvider`

Follow-up phases will register `sms:*`, `email:*`, `ai:*`, `maps:*`, `calendars:*`, `storage:*`, and additional payment providers under the same base class.

### Invariants (locked by test)
1. Adapter constructor is stateless — no per-tenant state cached in memory.
2. Every method that talks to a provider re-reads the tenant's credential via `get_secret` (`_resolve_auth`); no in-flight caching means revocations take effect immediately.
3. Exception messages from third-party SDKs are wrapped as `TenantPaymentError("<op> failed: <ExceptionType>")` — the raw exception message never crosses the adapter boundary.
4. Webhook verification uses the **platform** secret (Stripe posts to the platform endpoint, the event body identifies the tenant via the `account` field for Connect events).

---

## `SmsProvider` + `EmailProvider` (I1.7.b · Feb-2026)
Sibling adapter families under `services/messaging/`.

### `SmsProvider` (`services/messaging/sms/base.py`)
```python
class SmsProvider(ABC):
    provider_key: str
    config_fields: Dict[str, {"required": bool, "secret": bool, "label": str}]

    async def send_sms(*, tenant_id, to, body, media_urls=None, metadata=None) -> SmsResult: ...
    async def get_status(*, tenant_id, message_id) -> SmsStatus: ...
    async def verify_webhook(*, payload, headers) -> SmsInboundEvent: ...
    async def test_connection(*, tenant_id) -> ConnectionHealth: ...
```

### `EmailProvider` (`services/messaging/email/base.py`)
```python
class EmailProvider(ABC):
    provider_key: str
    config_fields: Dict[str, {"required": bool, "secret": bool, "label": str}]

    async def send_email(*, tenant_id, to, subject, html_body=None, text_body=None,
                          from_addr=None, attachments=None, reply_to=None, metadata=None) -> EmailResult: ...
    async def get_status(*, tenant_id, message_id) -> EmailStatus: ...
    async def verify_webhook(*, payload, headers) -> EmailInboundEvent: ...
    async def test_connection(*, tenant_id) -> ConnectionHealth: ...
```

### Concrete implementations
| Kind | Key | File |
| --- | --- | --- |
| SMS   | `twilio`      | `sms/twilio_provider.py` |
| SMS   | `textmagic`   | `sms/textmagic_provider.py` |
| SMS   | `ringcentral` | `sms/ringcentral_provider.py` |
| Email | `resend`      | `email/resend_provider.py` |
| Email | `sendgrid`    | `email/sendgrid_provider.py` |
| Email | `postmark`    | `email/postmark_provider.py` |
| Email | `mailgun`     | `email/mailgun_provider.py` |
| Email | `smtp`        | `email/smtp_provider.py` |

### Config storage shape
Providers with multiple secret fields (SMTP, RingCentral, Twilio, etc.) serialise their config as a compact JSON object and pass it into `services.secrets.put_secret` as a single plaintext blob. `services.messaging._helpers.save_provider_config` handles validation + JSON serialisation, and `load_provider_config` handles inverse. Legacy rows storing a bare api-key string are auto-wrapped as `{"api_key": <str>}` at read-time so we never break rotation semantics.

### Error taxonomy
* `MessagingError` — base class for adapter failures.
* `TenantMessagingNotConnected` — no saved config AND platform fallback disabled.
* `UnknownMessagingProvider` — unknown provider key on registry lookup.
* `InvalidProviderConfig` — save-time validation failure (message names fields, NEVER echoes values).

### Registry (`services/messaging/{sms,email}/registry.py`)
```python
register_sms_provider(key, cls) / register_email_provider(key, cls)
get_sms_provider(key) / get_email_provider(key)              # raises UnknownMessagingProvider
list_registered_sms_provider_keys() / list_registered_email_provider_keys()
get_tenant_sms_provider(tenant_id) / get_tenant_email_provider(tenant_id)
    # Scans the tenant's saved rows and returns the first connected
    # provider instance. Returns None when the tenant has no config —
    # dispatch layer falls back to the platform default.
```

### Dispatch shim (`services/messaging/dispatch.py`)
```python
dispatch_sms(*, tenant_id, to, body, media_urls=None, metadata=None, db=None) -> dict
dispatch_email(*, tenant_id, to, subject, html_body=None, text_body=None,
                from_addr=None, from_name=None, attachments=None, reply_to=None,
                metadata=None, db=None) -> dict
```
Returns the tenant provider's result on the hot path, else falls back to the legacy platform adapter and appends to `platform_messaging_fallback_log`. Return shape mirrors the legacy adapter for drop-in compatibility.

### Invariants (locked by test)
1. `SmsProvider` / `EmailProvider` cannot be instantiated (abstract).
2. Every concrete provider declares a `provider_key` + non-empty `config_fields` and implements all four async methods.
3. SMS + Email provider key-spaces are disjoint.
4. Registry lookups are cached; `reset_cache_for_tests()` clears them.
5. `save_provider_config` refuses to persist a config missing any `required=True` field; error message names each missing field, never echoes any provided value.
6. `save_provider_config` serialises config as compact JSON (sort_keys=True) then encrypts via `services.secrets.put_secret`.
7. Rotation via `save_provider_config` with the same `(tenant_id, provider_key)` atomically overwrites — the prior plaintext is unrecoverable.
8. `dispatch_*` calls the tenant's provider when configured; else calls the legacy platform adapter AND logs one entry to `platform_messaging_fallback_log`; else returns `{"status": "failed"}` when both are unavailable (fallback disabled).
9. Adapter error messages wrap exceptions as `MessagingError("<op> failed: <ExceptionType>")` — never the raw SDK message + never the api_key.
