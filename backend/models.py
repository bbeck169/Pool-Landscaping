from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator
from typing import List, Optional, Any
import re


def validate_password_strength(v: str) -> str:
    """Password policy for SOC2/ISO 27001 technical controls."""
    if v is None or len(v) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain an uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain a lowercase letter")
    if not re.search(r"[0-9]", v):
        raise ValueError("Password must contain a number")
    return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class CustomerIn(BaseModel):
    name: str
    email: Optional[str] = ""
    phone: Optional[str] = ""
    address: Optional[str] = ""
    billing_address: Optional[str] = ""
    gate_code: Optional[str] = ""
    notes: Optional[str] = ""
    avatar: Optional[str] = ""
    # Phase 2 additions:
    tags: Optional[List[str]] = []           # e.g. ["VIP", "Specialty"] plus arbitrary custom tags
    alert_email: Optional[str] = ""          # after-hours escalation channel
    alert_phone: Optional[str] = ""          # after-hours SMS escalation
    waitlisted: Optional[bool] = False       # unscheduled customer flagged as waiting for a slot
    secondary_addresses: Optional[List[str]] = []


class CustomerBulkAction(BaseModel):
    ids: List[str]
    action: str                                   # "add_tag" | "remove_tag" | "add_waitlist" | "remove_waitlist" | "delete"
    tag: Optional[str] = None


class TechnicianIn(BaseModel):
    name: str
    email: Optional[str] = ""
    phone: Optional[str] = ""
    specialty: Optional[str] = "Pool Service"
    avatar: Optional[str] = ""


class JobIn(BaseModel):
    title: str
    customer_id: str
    technician_id: Optional[str] = None
    address: Optional[str] = ""
    service_type: Optional[str] = "Pool Cleaning"
    scheduled_date: Optional[str] = None
    notes: Optional[str] = ""
    price: Optional[float] = 0.0
    status: Optional[str] = "pending"


class JobUpdate(BaseModel):
    status: Optional[str] = None
    technician_id: Optional[str] = None
    notes: Optional[str] = None
    scheduled_date: Optional[str] = None


class JobArriveIn(BaseModel):
    lat: float
    lng: float
    site_lat: Optional[float] = None
    site_lng: Optional[float] = None
    price: Optional[float] = None


class FieldReportUpdate(BaseModel):
    checklist: Optional[List[dict]] = None
    chemical_readings: Optional[dict] = None
    chemicals_added: Optional[List[dict]] = None
    customer_notes: Optional[str] = None
    internal_notes: Optional[str] = None


class LineItem(BaseModel):
    description: str
    quantity: float = 1
    unit_price: float = 0.0
    category: str = "Pool"


class QuoteIn(BaseModel):
    customer_id: str
    title: str
    doc_type: str = "quote"  # quote | invoice
    line_items: List[LineItem] = []
    tax_rate: float = 0.0
    due_date: Optional[str] = None  # YYYY-MM-DD (invoices)
    notes: Optional[str] = ""
    terms: Optional[str] = None  # None → auto-fill from /settings/terms defaults


class QuoteUpdate(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None
    terms: Optional[str] = None
    tax_rate: Optional[float] = None
    due_date: Optional[str] = None
    line_items: Optional[List[LineItem]] = None


class TermsSettingsIn(BaseModel):
    default_quote_terms: Optional[str] = None
    default_invoice_terms: Optional[str] = None


class RecordPaymentIn(BaseModel):
    amount: float


class CategoryIn(BaseModel):
    name: str


class SetupSessionReq(BaseModel):
    return_url: str
    customer_id: Optional[str] = None


class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: Optional[str] = ""
    address: Optional[str] = ""

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return validate_password_strength(v)


class CreateLoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return validate_password_strength(v)


class CustomerProfileUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    billing_address: Optional[str] = None
    gate_code: Optional[str] = None
    avatar: Optional[str] = None


class PhotoIn(BaseModel):
    data: str  # base64 data URI
    label: Optional[str] = "photo"


class ServiceIssueIn(BaseModel):
    description: str
    cost: Optional[float] = None
    photo: Optional[str] = None  # base64 data URI


class ServiceRequestIn(BaseModel):
    service_type: str = "Pool Cleaning"
    title: Optional[str] = ""
    scheduled_date: Optional[str] = None
    notes: Optional[str] = ""


class LeadIn(BaseModel):
    name: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    source: Optional[str] = "Website"
    status: Optional[str] = "new"  # new | contacted | quoted | won | lost
    notes: Optional[str] = ""
    est_value: Optional[float] = 0.0
    address: Optional[str] = ""
    lat: Optional[float] = None
    lng: Optional[float] = None


class LeadUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


class ItemIn(BaseModel):
    name: str
    category: Optional[str] = "Service"
    unit: Optional[str] = "each"
    unit_price: float = 0.0
    taxable: Optional[bool] = True


class BillingPlanIn(BaseModel):
    customer_id: str
    service: Optional[str] = "Monthly Pool Service"
    frequency: Optional[str] = "monthly"  # weekly | monthly | quarterly
    amount: float = 0.0
    next_run: Optional[str] = None
    active: Optional[bool] = True


class BillingPlanUpdate(BaseModel):
    service: Optional[str] = None
    frequency: Optional[str] = None
    amount: Optional[float] = None
    next_run: Optional[str] = None
    active: Optional[bool] = None


class RepairIn(BaseModel):
    customer_id: str
    equipment: Optional[str] = "Pump"
    issue: str
    technician_id: Optional[str] = None
    cost: Optional[float] = 0.0
    status: Optional[str] = "open"  # open | diagnosing | awaiting_parts | repaired
    photos: Optional[List[str]] = []  # base64 data URIs


class RepairUpdate(BaseModel):
    status: Optional[str] = None
    technician_id: Optional[str] = None
    cost: Optional[float] = None
    issue: Optional[str] = None


class FormIn(BaseModel):
    name: str
    description: Optional[str] = ""
    slug: Optional[str] = None
    status: Optional[str] = "draft"  # draft | published
    fields: List[Any] = Field(default_factory=list)  # [{id,name,label,type,required,options,...}]
    destination: Optional[str] = "lead"  # lead | customer | quote_request
    notify_emails: Optional[List[str]] = None
    redirect_url: Optional[str] = None
    model_config = {"extra": "allow"}


class FormSubmitIn(BaseModel):
    values: dict = {}


class AutomationIn(BaseModel):
    name: str
    trigger: str  # e.g. lead_created, job_completed, invoice_unpaid
    action: str   # e.g. send_welcome_sms, request_review, send_reminder
    active: Optional[bool] = True


class AutomationUpdate(BaseModel):
    active: Optional[bool] = None
    name: Optional[str] = None
    trigger: Optional[str] = None
    action: Optional[str] = None


class CampaignIn(BaseModel):
    channel: Optional[str] = "email"  # email | sms
    subject: str
    body: Optional[str] = ""
    audience: Optional[str] = "all_customers"


class ReviewIn(BaseModel):
    customer_name: str
    rating: int = 5
    text: Optional[str] = ""
    source: Optional[str] = "Google"


class ReviewRespond(BaseModel):
    response: str


class CheckinIn(BaseModel):
    job_id: Optional[str] = None
    address: Optional[str] = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    note: Optional[str] = ""


class AIChatIn(BaseModel):
    employee_id: str
    message: str
    session_id: Optional[str] = None


class AccessUpdate(BaseModel):
    role: str
    module: str
    enabled: bool


class CheckoutRequest(BaseModel):
    success_url: str
    cancel_url: str


class MessageIn(BaseModel):
    text: str


class BookIn(BaseModel):
    date: str
    label: str


class SeoKeywordReq(BaseModel):
    seed: str
    location: Optional[str] = "Vistancia, Arizona"


class SeoArticleReq(BaseModel):
    keyword: str
    title: Optional[str] = None
    tone: Optional[str] = "friendly, professional"
    word_count: Optional[int] = 800


class SeoAuditReq(BaseModel):
    keyword: str
    content: Optional[str] = None
    article_id: Optional[str] = None


class WpSettingsIn(BaseModel):
    url: str
    username: str
    app_password: str


class SeoPublishReq(BaseModel):
    status: Optional[str] = "publish"  # draft | publish


class SeoScheduleReq(BaseModel):
    mode: Optional[str] = "auto"  # auto (weekly drip) | manual (explicit date)
    scheduled_for: Optional[str] = None  # ISO datetime, required for manual mode


class SeoScheduleSettings(BaseModel):
    enabled: Optional[bool] = True
    paused: Optional[bool] = False
    day_of_week: Optional[int] = 0  # 0=Mon ... 6=Sun
    hour: Optional[int] = 9
    minute: Optional[int] = 0
    publish_as: Optional[str] = "draft"  # draft | publish


class GbpSettingsIn(BaseModel):
    client_id: str
    client_secret: str
    redirect_uri: str


class GbpPostIn(BaseModel):
    location: str  # full resource name: accounts/x/locations/y
    summary: str
    cta_url: Optional[str] = None
    action_type: Optional[str] = "LEARN_MORE"  # LEARN_MORE | BOOK | ORDER | CALL | SIGN_UP


class GbpReplyIn(BaseModel):
    review_name: str  # full resource name of the review
    comment: str


class GbpAiPostReq(BaseModel):
    article_id: str


class GbpAiReplyReq(BaseModel):
    review_text: Optional[str] = ""
    rating: Optional[int] = 5
    reviewer_name: Optional[str] = ""


class GbpBusinessUpdate(BaseModel):
    location: str
    phone: Optional[str] = None
    website: Optional[str] = None
    regular_hours: Optional[dict] = None  # passthrough {periods:[...]} per GBP schema


class GbpAutopost(BaseModel):
    enabled: bool


class GbpCalendarEdit(BaseModel):
    summary: Optional[str] = None
    cta_url: Optional[str] = None


class CardCompanyIn(BaseModel):
    name: Optional[str] = None
    region: Optional[str] = None
    tagline: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    google_review: Optional[str] = None
    logo: Optional[str] = None  # base64 data URI


class CardPersonalIn(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class ConvertJobIn(BaseModel):
    service_type: Optional[str] = "Pool Service"
    scheduled_date: Optional[str] = None
    price: Optional[float] = None
    technician_id: Optional[str] = None


class ConvertQuoteIn(BaseModel):
    title: Optional[str] = None
    unit_price: Optional[float] = None
    tax_rate: Optional[float] = 0.0


class DocumentIn(BaseModel):
    customer_id: str
    name: str
    type: Optional[str] = "document"
    data: str  # base64 data URI or external URL


class MaintScheduleIn(BaseModel):
    customer_id: str
    type: str  # filter | salt_cell
    scheduled_date: str  # YYYY-MM-DD
    technician_id: Optional[str] = None
    interval_days: Optional[int] = None  # optionally update the pool's cadence


class MaintSettingsIn(BaseModel):
    filter_interval_days: Optional[int] = None
    salt_cell_interval_days: Optional[int] = None


class MaintBulkIn(BaseModel):
    scheduled_date: str  # YYYY-MM-DD
    technician_id: Optional[str] = None


class PunchIn(BaseModel):
    lat: float
    lng: float


class CoverageIn(BaseModel):
    source_technician_id: str
    target_technician_id: str
    scope: str = "day"  # day | week
    date: Optional[str] = None  # YYYY-MM-DD; required for scope=day, anchor for scope=week


class EstimateLineIn(BaseModel):
    category: str = "Material"  # Material | Labor | Subcontractor | Equipment | Other
    description: str = ""
    quantity: float = 1
    unit_cost: float = 0.0
    item_id: Optional[str] = None


class EstimateIn(BaseModel):
    customer_id: str
    title: str
    line_items: List[EstimateLineIn] = []
    overhead_pct: float = 0.0
    margin_pct: float = 0.0
    notes: Optional[str] = ""
    terms: Optional[str] = None  # None → auto-fill from /settings/terms defaults


class EstimateSettingsIn(BaseModel):
    overhead_pct: Optional[float] = None
    margin_pct: Optional[float] = None


class EstimateTemplateIn(BaseModel):
    name: str
    line_items: List[EstimateLineIn] = []
    overhead_pct: float = 0.0
    margin_pct: float = 0.0


class D2DKnockIn(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    address: Optional[str] = ""
    name: Optional[str] = ""
    phone: Optional[str] = ""
    disposition: str = "not_home"  # not_home | not_interested | callback | interested | sold
    notes: Optional[str] = ""
    zpid: Optional[str] = None  # Zillow property id when logged from a sold-lead pin
    sold_price: Optional[float] = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def _outcome_alias(cls, data):
        # Accept `outcome` as an alias for `disposition` (mobile clients).
        if isinstance(data, dict) and "outcome" in data and not data.get("disposition"):
            data = {**data, "disposition": data["outcome"]}
        return data


class D2DKnockUpdate(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    address: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    disposition: Optional[str] = None
    notes: Optional[str] = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def _outcome_alias(cls, data):
        if isinstance(data, dict) and "outcome" in data and not data.get("disposition"):
            data = {**data, "disposition": data["outcome"]}
        return data


class MaintLogIn(BaseModel):
    psi: Optional[float] = None
    filter_condition: Optional[str] = None
    salt_ppm: Optional[float] = None
    cell_condition: Optional[str] = None
    notes: Optional[str] = None
    photos: Optional[List[dict]] = None  # [{label, data(base64)}]
