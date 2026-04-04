# BFG2 Framework — Models & API Reference

Complete reference for all models, fields, and API endpoints in this Django server.
All API routes are prefixed with `/api/v1/`. All models are workspace-scoped via `workspace` ForeignKey.

## Authentication

| Method | How |
|--------|-----|
| JWT Bearer | `Authorization: Bearer <token>` — obtain at `POST /api/v1/auth/token/` |
| API Key | `X-Api-Key: <prefix>` + `X-Api-Secret: <secret>` |
| Session | Cookie (Django sessions) |

Multi-tenancy: `WorkspaceMiddleware` resolves workspace from `X-Workspace-Id` header, `workspace_id` query param, or domain.

---

## Module: `bfg.common` — Core Infrastructure

### Workspace
```
name            CharField(255)
slug            SlugField(100, unique)
domain          CharField(255, blank)
email           EmailField(blank)
phone           CharField(50, blank)
is_active       BooleanField(default=True)
settings        JSONField(default=dict)
created_at      DateTimeField
updated_at      DateTimeField(auto_now)
```

### User *(extends AbstractUser)*
```
phone           CharField(50, blank)
avatar          ImageField(upload_to='avatars/')
default_workspace   FK→Workspace(null, related='default_users')
platform_user_id    CharField(255, unique, null)
language        CharField(10, default='en')
timezone_name   CharField(50, default='UTC')
updated_at      DateTimeField(auto_now)
```

### Customer
```
workspace       FK→Workspace(related='customers')
user            FK→User(related='customer_profiles')
customer_number CharField(50, blank)
company_name    CharField(255, blank)
tax_number      CharField(100, blank)
credit_limit    DecimalField(10,2, default=0)
balance         DecimalField(10,2, default=0)
is_active       BooleanField(default=True)
is_verified     BooleanField(default=False)
verified_at     DateTimeField(null)
notes           TextField(blank)
gateway_metadata    JSONField(default=dict)   ← Stripe customer ID etc.
addresses       GenericRelation→Address
created_at / updated_at
```

### Address *(generic — links to Customer, Order, etc.)*
```
workspace       FK→Workspace(related='addresses')
content_type    FK→ContentType(null)   ← generic target type
object_id       PositiveIntegerField(null)
content_object  GenericForeignKey
full_name       CharField(255)
phone           CharField(50)
email           EmailField(blank)
company         CharField(255, blank)
address_line1   CharField(255)
address_line2   CharField(255, blank)
city            CharField(100)
state           CharField(100, blank)
postal_code     CharField(20)
country         CharField(2)           ← ISO 3166-1 alpha-2
latitude / longitude  DecimalField(10,7, null)
notes           TextField(blank)
is_default      BooleanField(default=False)
created_at / updated_at
```

### Settings *(one-to-one with Workspace)*
```
workspace       OneToOneField→Workspace(related='workspace_settings')
site_name / site_description / logo / favicon
default_language    CharField(10, default='en')
supported_languages JSONField(default=list)
default_currency    CharField(3)
default_timezone    CharField(50)
contact_email / support_email / contact_phone
facebook_url / twitter_url / instagram_url  URLField
features        JSONField(default=dict)
custom_settings JSONField(default=dict)
updated_at
```

### AuditLog
```
workspace       FK→Workspace(null, related='audit_logs')
user            FK→User(null)
action          CharField choices: create|update|delete|login|logout|other
description     TextField(blank)
content_type    FK→ContentType(null)
object_id       PositiveIntegerField(null)
object_repr     CharField(255, blank)
changes         JSONField(default=dict)
ip_address      GenericIPAddressField(null)
user_agent      TextField(blank)
created_at      DateTimeField(db_index)
```

### APIKey
```
workspace       FK→Workspace(related='api_keys')
name            CharField(255)
prefix          CharField(16, unique)         ← used as X-Api-Key header value
secret_hash     CharField(64)                 ← SHA-256 of secret (never stored plain)
is_active       BooleanField(default=True)
created_by      FK→User(null, related='created_api_keys')
last_used_at    DateTimeField(null)
expires_at      DateTimeField(null)
created_at / updated_at
```

### Media
```
workspace       FK→Workspace(related='common_media_files')
file            FileField(blank)
external_url    URLField(blank)
media_type      CharField choices: image|video|model_3d|external_video (default=image)
alt_text        CharField(255, blank)
width / height  IntegerField(null)
uploaded_by     FK→User(null, related='common_media_uploads')
created_at / updated_at
```

### MediaLink *(generic — attaches Media to any model)*
```
media           FK→Media(related='links')
content_type    FK→ContentType
object_id       PositiveIntegerField
content_object  GenericForeignKey
position        PositiveSmallIntegerField(default=100)
description     CharField(255, blank)
created_at / updated_at
```

### StaffRole
```
workspace       FK→Workspace(related='staff_roles')
name            CharField(100)
code            CharField(50)
description     TextField(blank)
permissions     JSONField(default=dict)
is_system       BooleanField(default=False)
is_active       BooleanField(default=True)
created_at / updated_at
```

### StaffMember
```
workspace       FK→Workspace(related='staff_members')
user            FK→User(related='staff_memberships')
role            FK→StaffRole(on_delete=PROTECT, related='staff_members')
is_active       BooleanField(default=True)
created_at / updated_at
```

### CustomerSegment
```
workspace       FK→Workspace(related='customer_segments')
name            CharField(255)
query           JSONField(default=dict)   ← dynamic filter rules
is_active       BooleanField(default=True)
created_at / updated_at
```

### CustomerTag
```
workspace       FK→Workspace(related='customer_tags')
name            CharField(50)
customers       M2M→Customer(related='tags')
created_at
```

### API Endpoints — `/api/v1/`
```
workspaces/              GET list, POST create, GET/PUT/PATCH/DELETE detail
customers/               CRUD
addresses/               CRUD
settings/                CRUD (singleton per workspace)
email-configs/           CRUD
users/                   CRUD
customer-segments/       CRUD
customer-tags/           CRUD
staff-roles/             CRUD
api-keys/                CRUD
me/                      GET/PUT/PATCH (current user profile)
me/addresses/            CRUD
me/orders/               GET list/detail
me/payment-methods/      CRUD
me/payments/             CRUD
me/invoices/             CRUD
me/tickets/              CRUD
me/settings/             GET/PUT/PATCH
me/dashboard-stats/      GET
me/support-options/      GET
me/change-password/      POST
me/reset-password/       POST
me/avatar/               POST (upload)
options/                 GET (workspace options / enums)
countries/               GET (country list)
```

---

## Module: `bfg.web` — CMS & Website

### Site
```
workspace       FK→Workspace(related='sites')
name            CharField(100)
domain          CharField(255, unique)
theme           FK→Theme(null, related='sites')
default_language    CharField(10, default='en')
languages       JSONField(default=list)
site_title      CharField(255)
site_description    TextField(blank)
notification_config JSONField(default=dict)
is_active       BooleanField(default=True)
is_default      BooleanField(default=False)
created_at / updated_at
```

### Theme
```
workspace       FK→Workspace(null, related='themes')
name / code     CharField
description     TextField(blank)
template_path   CharField(255)
logo / favicon  ImageField
primary_color   CharField(20, default='#007bff')
secondary_color CharField(20, default='#6c757d')
homepage_title / homepage_subtitle / homepage_text / homepage_image
custom_css / custom_js  TextField(blank)
config          JSONField(default=dict)
is_active       BooleanField(default=True)
created_at / updated_at
```

### Page
```
workspace       FK→Workspace(related='pages')
title           CharField(255)
slug            SlugField(255)
content         TextField
excerpt         TextField(blank)
blocks          JSONField(default=list)   ← block-based content
parent          FK→self(null, related='children')
template        CharField(100, default='default')
meta_title / meta_description / meta_keywords
status          CharField choices: draft|published|archived (default=draft)
published_at    DateTimeField(null)
is_featured     BooleanField(default=False)
allow_comments  BooleanField(default=False)
order           PositiveSmallIntegerField(default=100)
language        CharField(10)
created_at / updated_at
created_by      FK→User(related='pages_created')
```

### Post *(blog/news)*
```
workspace       FK→Workspace(related='posts')
title / slug / content / excerpt
cover_image     ImageField(blank)
categories      M2M→Category(related='posts')
tags            M2M→Tag(related='posts')
status          CharField choices: draft|published|archived
published_at    DateTimeField(null)
is_featured     BooleanField
language        CharField(10)
author          FK→User(null, related='posts_authored')
created_at / updated_at
```

### Category / Tag / Menu / MenuItem
*(Standard CMS hierarchy models — name, slug, parent, order, is_active, language)*

### NewsletterSubscription
```
workspace       FK→Workspace(related='newsletter_subscriptions')
email           EmailField
first_name / last_name  CharField(blank)
is_active       BooleanField(default=True)
subscribed_at / unsubscribed_at  DateTimeField
unsubscribe_token   CharField(unique)
```

### Booking / BookingTimeSlot
```
timeslot: workspace, date, start_time, end_time, capacity, is_active
booking:  workspace, customer, timeslot, status(pending|confirmed|cancelled), notes
```

### API Endpoints — `/api/v1/web/`
```
sites/                   CRUD
themes/                  CRUD
languages/               CRUD
pages/                   CRUD
posts/                   CRUD
media/                   CRUD
categories/              CRUD
tags/                    CRUD
menus/                   CRUD
inquiries/               CRUD
timeslots/               CRUD
bookings/                CRUD
newsletter-subscriptions/    CRUD
newsletter-templates/        CRUD
newsletter-sends/            CRUD
newsletter-send-logs/        CRUD
feedback/                POST
blocks/types/            GET
blocks/validate/         POST
newsletter/unsubscribe/  GET
```

---

## Module: `bfg.shop` — E-commerce

### ProductCategory
```
workspace       FK→Workspace(related='product_categories')
name / slug     CharField
description     TextField(blank)
parent          FK→self(null, related='children')
icon            CharField(50, blank)
image           ImageField
order           PositiveSmallIntegerField(default=100)
is_active       BooleanField
rules           JSONField(default=list)     ← auto-categorisation rules
rule_match_type CharField choices: all|any (default=all)
language        CharField(10)
```

### Product
```
workspace       FK→Workspace(related='products')
name / slug     CharField
sku / barcode   CharField(blank)
product_type    CharField choices: physical|digital|service|subscription (default=physical)
description     TextField(blank)
short_description   CharField(255, blank)
price           DecimalField(10,2)
compare_price   DecimalField(10,2, null)
cost            DecimalField(10,2, null)
is_subscription BooleanField(default=False)
subscription_plan   FK→SubscriptionPlan(null)
condition       CharField choices: new|like_new|good|fair|poor (blank)  ← for resale
categories      M2M→ProductCategory(related='products')
tags            M2M→ProductTag(related='products')
finance_code    FK→FinancialCode(null)
track_inventory BooleanField(default=True)
stock_quantity  IntegerField(default=0)
low_stock_threshold IntegerField(default=10)
requires_shipping   BooleanField(default=True)
weight          DecimalField(10,2, null)
meta_title / meta_description
is_active       BooleanField(default=True)
is_featured     BooleanField(default=False)
language        CharField(10)
created_at / updated_at
media_links     GenericRelation→MediaLink
```

### ProductVariant
```
product         FK→Product(related='variants')
sku             CharField(100)
name            CharField(255)
options         JSONField(default=dict)   ← e.g. {"size": "L", "color": "red"}
price           DecimalField(10,2, null)  ← overrides product price if set
compare_price   DecimalField(10,2, null)
stock_quantity  IntegerField(default=0)
weight          DecimalField(10,2, null)
is_active       BooleanField
order           PositiveSmallIntegerField(default=100)
```

### VariantInventory
```
variant         FK→ProductVariant(related='inventory')
warehouse       FK→Warehouse(related='variant_inventory')
quantity        IntegerField(default=0)
reserved        IntegerField(default=0)   ← held for pending orders
updated_at      auto_now
```

### Order
```
workspace       FK→Workspace(related='orders')
customer        FK→Customer(on_delete=PROTECT, related='orders')
store           FK→Store(on_delete=PROTECT, related='orders')
sales_channel   FK→SalesChannel(null)
coupon          FK→Coupon(null)
freight_service FK→FreightService(null)
order_number    CharField(50, unique)
status          CharField choices: pending|processing|shipped|delivered|cancelled|refunded
payment_status  CharField choices: pending|paid|failed|refunded
subtotal / shipping_cost / tax / discount / total   DecimalField(10,2)
shipping_address    FK→Address(on_delete=PROTECT)
billing_address     FK→Address(on_delete=PROTECT)
customer_note / admin_note  TextField(blank)
created_at / updated_at
paid_at / shipped_at / delivered_at  DateTimeField(null)
```

### OrderItem
```
order           FK→Order(related='items')
product         FK→Product(on_delete=PROTECT)
variant         FK→ProductVariant(null)
product_name / variant_name / sku   CharField(snapshot at order time)
quantity        PositiveIntegerField
price           DecimalField(10,2)
subtotal        DecimalField(10,2)
```

### Cart / CartItem
```
cart:  workspace, customer(null for guest), session_key(db_index), created_at/updated_at
item:  cart, product, variant(null), quantity, price, created_at/updated_at
```

### ProductReview
```
workspace, product, customer, rating(1-5), title, body, is_verified, is_published
created_at / updated_at
```

### SubscriptionPlan
```
workspace       FK→Workspace(related='subscription_plans')
name / description
price           DecimalField(10,2)
interval        CharField choices: day|week|month|year (default=month)
interval_count  PositiveIntegerField(default=1)
trial_period_days   PositiveIntegerField(default=0)
features        JSONField(default=list)
is_active       BooleanField
created_at / updated_at
```

### Subscription
```
workspace / customer / plan
status          CharField choices: active|trialing|past_due|cancelled|expired
start_date / end_date / trial_end / next_billing_date / cancelled_at
created_at / updated_at
```

### SalesChannel
```
workspace, name, code, description, is_active, config(JSONField), created_at/updated_at
```

### Store
```
workspace, name, code, address_line1..country, phone, email, is_active, is_default
```

### Wishlist
```
workspace, customer, product(M2M), created_at/updated_at
```

### Return / ReturnLineItem
```
return:     workspace, order, customer, status(pending|approved|rejected|completed),
            reason, notes, created_at/updated_at
line_item:  return_obj, order_item, quantity, condition, reason(blank)
```

### API Endpoints — `/api/v1/`
```
products/                CRUD + custom actions
products/categories/     CRUD (also nested under products/)
products/tags/           CRUD
categories/              CRUD
variants/                CRUD
stores/                  CRUD
carts/                   CRUD
orders/                  CRUD
reviews/                 CRUD
media/                   CRUD
product-media/           CRUD
sales-channels/          CRUD
subscription-plans/      CRUD
channel-listings/        CRUD
collections/             CRUD
returns/                 CRUD
return-items/            CRUD
order-packages/          CRUD
wishlists/               CRUD
store/                   Storefront endpoints (public-facing)
```

---

## Module: `bfg.delivery` — Logistics & Shipping

### Warehouse
```
workspace       FK→Workspace(related='warehouses')
name / code     CharField
address_line1..country  CharField (full address)
latitude / longitude  DecimalField(10,7, null)
phone / email
is_active / is_default  BooleanField
created_at / updated_at
```

### StorageLocation
```
warehouse       FK→Warehouse(related='locations')
code / description
is_active       BooleanField
```

### Carrier
```
workspace       FK→Workspace(related='carriers')
name / code     CharField
carrier_type    CharField(50, blank)   ← e.g. 'parcelport', 'starshipit'
config          JSONField(default=dict)   ← live credentials
test_config     JSONField(default=dict)   ← sandbox credentials
is_test_mode    BooleanField(default=False)
tracking_url_template   CharField(500, blank)
is_active       BooleanField
created_at / updated_at
```

### FreightService
```
workspace / carrier
name / code / description
base_price / price_per_kg   DecimalField(10,2)
estimated_days_min / max    PositiveIntegerField
min_weight / max_weight     DecimalField(10,2)
config          JSONField(default=dict)
transport_type  CharField choices: air|sea|road|rail|other
delivery_zones  M2M→DeliveryZone(related='freight_services')
is_active / order
```

### Consignment
```
workspace, order(FK), carrier, freight_service
tracking_number, status(FK→FreightState), barcode
sender_address / recipient_address  FK→Address
packages (related), notes (GenericRelation→ConsignmentNote)
created_at / updated_at / dispatched_at / delivered_at
```

### Package
```
consignment     FK→Consignment(null)
order           FK→Order(null)
packaging_type  FK→PackagingType(null)
weight / length / width / height  DecimalField
tracking_number CharField(blank)
```

### DeliveryZone
```
workspace, name, code, description
countries       JSONField(default=list)   ← list of ISO country codes
postcodes       JSONField(default=list)
is_active       BooleanField
```

### TrackingEvent
```
consignment, event_type, description, location, timestamp, raw_data(JSONField)
```

### API Endpoints — `/api/v1/`
```
warehouses/              CRUD
consignments/            CRUD
carriers/                CRUD
freight-services/        CRUD
packaging-types/         CRUD
freight-statuses/        CRUD
tracking-events/         CRUD
delivery-zones/          CRUD
packages/                CRUD
package-templates/       CRUD
```

---

## Module: `bfg.finance` — Payments & Billing

### Currency
```
code(3, unique), name, symbol, decimal_places(default=2), is_active
```

### PaymentGateway
```
workspace       FK→Workspace(related='payment_gateways')
name            CharField(255)
gateway_type    CharField choices: stripe|paypal|wechat|alipay|bank_transfer|custom
config          JSONField(default=dict)   ← live API keys
test_config     JSONField(default=dict)
is_active / is_test_mode  BooleanField
created_at / updated_at
```

### PaymentMethod *(saved cards / wallets)*
```
workspace / customer / gateway
method_type     CharField choices: card|bank|wallet
gateway_token   CharField(255)            ← Stripe PM ID etc.
cardholder_name CharField(255, blank)
card_brand      CharField choices: visa|mastercard|amex|discover|jcb|diners|unionpay|unknown
card_last4      CharField(4, blank)
card_exp_month / card_exp_year   PositiveSmallIntegerField(null)
display_info    CharField(255, blank)
billing_address FK→Address(null)
is_default / is_active  BooleanField
created_at / updated_at
```

### Invoice
```
workspace / customer
invoice_number  CharField(unique)
status          CharField choices: draft|sent|paid|overdue|cancelled|void
subtotal / tax / discount / total  DecimalField(10,2)
due_date        DateField(null)
paid_at         DateTimeField(null)
notes / terms   TextField(blank)
financial_code  FK→FinancialCode(null)
created_at / updated_at
```

### InvoiceItem
```
invoice, description, quantity, unit_price, subtotal, tax_rate(FK, null), financial_code(FK, null)
```

### Payment
```
workspace / customer / order(null) / invoice(null) / payment_method(null)
gateway         FK→PaymentGateway
gateway_transaction_id  CharField(unique, null)
amount          DecimalField(10,2)
currency        FK→Currency
status          CharField choices: pending|processing|completed|failed|refunded|cancelled
payment_type    CharField choices: sale|auth|capture|void|refund
gateway_response    JSONField(default=dict)
created_at / updated_at / processed_at(null)
```

### Refund
```
payment         FK→Payment(related='refunds')
amount          DecimalField(10,2)
reason          TextField(blank)
status          CharField choices: pending|completed|failed
gateway_refund_id   CharField(blank)
created_at / processed_at(null)
```

### Wallet
```
workspace / customer
balance         DecimalField(10,2, default=0)
currency        FK→Currency
is_active       BooleanField
created_at / updated_at
```

### Transaction *(wallet movements)*
```
workspace / wallet / customer
transaction_type    CharField choices: credit|debit|refund|withdrawal|adjustment
amount          DecimalField(10,2)
balance_after   DecimalField(10,2)
description     TextField(blank)
reference_order FK→Order(null)
created_at
```

### WithdrawalRequest
```
workspace / customer / wallet
amount          DecimalField(10,2)
status          CharField choices: pending|approved|rejected|completed
bank_details    JSONField(default=dict)
created_at / processed_at(null)
```

### TaxRate
```
workspace, name, rate(DecimalField 5,2), country(2), state(blank), is_active
```

### BillingCycle / BillingStatement
```
billing_cycle:      workspace, subscription, start_date, end_date, status
billing_statement:  billing_cycle, amount, status, due_date, paid_at
```

### API Endpoints — `/api/v1/`
```
invoices/                CRUD
payments/                CRUD
payment-methods/         CRUD
payment-gateways/        CRUD
currencies/              CRUD
brands/                  CRUD
financial-codes/         CRUD
tax-rates/               CRUD
transactions/            CRUD
wallets/                 CRUD
withdrawal-requests/     CRUD
```

---

## Module: `bfg.marketing` — Campaigns & Promotions

### Campaign
```
workspace / group(FK→CampaignGroup, null)
name            CharField(255)
campaign_type   CharField choices: email|sms|social|affiliate|other
description     TextField(blank)
start_date / end_date(null)  DateTimeField
budget          DecimalField(10,2, null)
utm_source / utm_medium / utm_campaign  CharField(blank)
is_active       BooleanField
requires_participation  BooleanField(default=False)
min_participants / max_participants  PositiveIntegerField(null)
promo_display_type  CharField(50, blank)
config          JSONField(default=dict)
created_at / updated_at / created_by(FK→User)
```

### DiscountRule
```
workspace, name
discount_type   CharField choices: percentage|fixed_amount|free_shipping|buy_x_get_y|other
discount_value  DecimalField(10,2)
apply_to        CharField choices: order|products|categories|other
products        M2M→Product(related='discount_rules')
categories      M2M→ProductCategory
minimum_purchase / maximum_discount  DecimalField(null)
config          JSONField(default=dict)
```

### Coupon
```
workspace / campaign(null) / discount_rule(FK)
code            CharField(unique)
coupon_type     CharField choices: single_use|multi_use|customer_specific
usage_limit     PositiveIntegerField(null)   ← null = unlimited
usage_count     PositiveIntegerField(default=0)
customer        FK→Customer(null)            ← customer-specific coupons
valid_from / valid_until  DateTimeField(null)
is_active       BooleanField
created_at / updated_at
```

### GiftCard
```
workspace / customer(null)
code            CharField(unique)
initial_balance / balance  DecimalField(10,2)
currency        FK→Currency
status          CharField choices: active|redeemed|expired|cancelled
valid_until     DateField(null)
created_at / updated_at
```

### ReferralProgram / Referral
```
program: workspace, name, reward_type, reward_value, min_purchase, is_active
referral: workspace, program, referrer(FK→Customer), referred(FK→Customer),
          status(pending|qualified|rewarded), order(FK, null), created_at
```

### CampaignParticipation / StampRecord
```
participation: workspace, campaign, customer, status(registered|qualified|coupon_issued|redeemed), order(null)
stamp: workspace, customer, campaign, stamps_earned, stamps_redeemed, created_at
```

### AffiliatePartner / Channel / ChannelLink / LinkClick
*(Affiliate tracking — partner → channels → links → clicks)*

### API Endpoints — `/api/v1/`
```
campaigns/                   CRUD
campaign-displays/           CRUD
campaign-participations/     CRUD
stamp-records/               CRUD
coupons/                     CRUD
gift-cards/                  CRUD
referral-programs/           CRUD
discount-rules/              CRUD
```

---

## Module: `bfg.support` — Help Desk

### SupportTicket
```
workspace / customer
ticket_number   CharField(50, unique)
subject         CharField(255)
description     TextField
category        FK→TicketCategory(null)
priority        FK→TicketPriority(null)
tags            M2M→TicketTag
status          CharField choices: new|open|pending|on_hold|resolved|closed
channel         CharField choices: email|web|phone|chat|social
assigned_to     FK→User(null)
team            FK→SupportTeam(null)
related_order   FK→Order(null)
created_at / updated_at
first_response_at / resolved_at / closed_at  DateTimeField(null)
```

### SupportTicketMessage
```
ticket          FK→SupportTicket(related='messages')
sender          FK→User(null)
is_staff_reply  BooleanField(default=False)
body            TextField
attachments     JSONField(default=list)
created_at
```

### TicketCategory / TicketPriority / TicketTag / SupportTeam
```
category:  workspace, name, description, order, is_active
priority:  workspace, name, level, color, response_time_hours, resolution_time_hours
tag:       workspace, name
team:      workspace, name, description, members(M2M→User), is_active
```

### SLA / KnowledgeBase
```
sla:            workspace, name, response_time_hours, resolution_time_hours, is_active
knowledge_base: workspace, category(FK), title, slug, content, status, is_featured
```

### API Endpoints — `/api/v1/support/`
```
tickets/                 CRUD
ticket-categories/       CRUD
ticket-priorities/       CRUD
options/                 GET (categories, priorities, teams)
```

---

## Module: `bfg.inbox` — Messaging & Notifications

### Message
```
workspace       FK→Workspace(related='messages')
subject         CharField(255)
message         TextField
message_type    CharField choices: notification|message|system|announcement
sender          FK→User(null)
action_url / action_label  (deep-link button)
related_content_type / related_object_id  (GenericFK to any model)
send_email / send_sms / send_push  BooleanField
send_*_at       DateTimeField(null)   ← scheduled send times
expires_at      DateTimeField(null)
created_at
```

### MessageTemplate
```
workspace / name / code / event(CharField 50)   ← event code e.g. 'order.created'
email_enabled / email_subject / email_body / email_html_body
app_message_enabled / app_message_title / app_message_body
sms_enabled / sms_body(max_length=160)
push_enabled / push_title / push_body
available_variables  JSONField(default=dict)   ← template variable docs
language        CharField(10)
is_active       BooleanField
created_at / updated_at
```

### MessageRecipient
```
message         FK→Message(related='recipients')
recipient       FK→Customer(related='received_messages')
is_read / is_archived / is_deleted  BooleanField
delivered_at    DateTimeField
read_at         DateTimeField(null)
```

### SMSMessage
```
workspace / customer
phone_number    CharField(20)
message         TextField(max_length=160)
status          CharField choices: pending|sent|delivered|failed
provider / provider_id  CharField
provider_response   JSONField(default=dict)
message_ref     FK→Message(null)
created_at / sent_at / delivered_at
```

### API Endpoints — `/api/v1/inbox/`
```
messages/                CRUD
templates/               CRUD
recipients/              CRUD
sms/                     CRUD
```

---

## Local App: `apps.platform` — SaaS Platform Management

Models: `WorkspaceProfile`, `Cluster`, `FeatureFlag`, `PlatformSubscription`, `PlatformBillingRecord`

### API Endpoints — `/api/v1/platform/`
```
workspaces/              GET list, POST create, GET/PUT/PATCH/DELETE detail
subscriptions/           GET list/detail, POST create
subscription-plans/      GET list/detail
webhooks/stripe/         POST (Stripe webhook)
auth/provision-user/     POST (internal — provision user from platform)
auth/provision-workspace/    POST (internal — provision workspace from platform)
```

---

## Auth Endpoints — `/api/v1/auth/`
```
register/                POST  {email, username, password1, password2}
forgot-password/         POST  {email}
reset-password-confirm/  POST  {uid, token, new_password1, new_password2}
verify-email/            POST  {key}
token/                   POST  {email, password} → {access, refresh}
token/refresh/           POST  {refresh} → {access}
token/verify/            POST  {token}
google/login/            GET   → redirect to Google OAuth
google/callback/         GET   → OAuth callback
facebook/login/          GET
facebook/callback/       GET
apple/login/             GET
apple/callback/          POST (CSRF-exempt)
```

---

## Common Patterns

**Pagination**: All list endpoints use page-number pagination. Default page size: 20. Query params: `?page=2&page_size=50`

**Filtering**: Most viewsets support `?search=`, `?ordering=`, and field-specific filters.

**Workspace isolation**: All data is automatically scoped to the current workspace. Staff can access the workspace derived from their token. API keys always resolve to their linked workspace.

**Storefront vs Admin API**: Storefront endpoints (`/api/v1/store/`) allow anonymous access. Admin endpoints require authentication.

**Docs**: Swagger UI at `/api/docs/` · ReDoc at `/api/redoc/`
