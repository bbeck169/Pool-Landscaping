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
