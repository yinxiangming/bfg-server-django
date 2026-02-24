# BFG2 Model Migration Mapping

## Overview

This document maps existing models from the `freight` app to their new locations in the BFG2 library. This will guide the migration process and help ensure data continuity.

## Migration Summary

| Source File | Models Count | Target Module | Notes |
|------------|--------------|---------------|-------|
| `freight/models/freight.py` | 10 models | `bfg2_delivery` | Core logistics models |
| `freight/models/promotions.py` | 3 models | `bfg2_promo` | Campaign and coupon system |
| `freight/models/finance.py` | 3 models | `bfg2_finance` | Payment and invoicing |
| `freight/models/support.py` | 2 models | `bfg2_support` | Support ticketing |

**Total**: 18 models to migrate + numerous new models to create

---

## Detailed Migration Map

### From freight/models/freight.py → bfg2_delivery

#### Warehouse
- **Status**: ✅ Direct migration
- **Changes**:
  - Added geo fields (latitude, longitude)
  - Added capacity tracking fields
  - Enhanced with `is_active` and `accepts_international` flags

#### Manifest
- **Status**: ✅ Direct migration with enhancements
- **Changes**:
  - Added `carrier` ForeignKey
  - Payments linked to `bfg2_finance.Payment`
  - Invoices linked to `bfg2_finance.Invoice`

#### ManifestStatus
- **Status**: ✅ Direct migration
- **Changes**:
  - Added `color` field for UI display
  - Enhanced notification settings

#### Consignment
- **Status**: ✅ Direct migration with enhancements
- **Changes**:
  - Added `carrier` and `carrier_tracking_number` fields
  - Added `order` link to `bfg2_shop.Order`
  - Added `service` link to `FreightService`
  - Enhanced financial tracking

#### ConsignmentStatus
- **Status**: ✅ Direct migration
- **Changes**:
  - Added notification settings
  - Added `color` field

#### Package
- **Status**: ✅ Direct migration
- **Changes**: Minimal changes, kept structure

#### PackageStatus
- **Status**: ✅ Direct migration
- **Changes**: Added `color` field

#### PackagingType
- **Status**: ✅ Direct migration
- **Changes**: Kept existing structure

#### FreightService
- **Status**: ✅ Direct migration
- **Changes**: Minimal changes

#### FreightLog
- **Status**: ✅ Renamed to `TrackingEvent`
- **Changes**:
  - Renamed for clarity
  - Added geographic tracking (latitude, longitude)
  - Enhanced with location field

---

### From freight/models/promotions.py → bfg2_promo

#### CampaignGroup
- **Status**: ✅ Direct migration
- **Changes**: Minimal changes

#### Campaign
- **Status**: ✅ Enhanced migration
- **Changes**:
  - Added discount type and value fields
  - Added min/max purchase conditions
  - Added product/category filters
  - Added usage limits
  - Added auto-apply functionality
  - Added trigger types

#### Coupon
- **Status**: ✅ Enhanced migration
- **Changes**:
  - Added `used_in_order` link
  - Added custom discount value override
  - Added expiry field

---

### From freight/models/finance.py → bfg2_finance

#### Invoice
- **Status**: ✅ Enhanced migration
- **Changes**:
  - Added invoice number (separate from reference)
  - Added detailed financial fields (subtotal, tax, discount)
  - Added status choices
  - Added order and consignment links
  - Added PDF file field

#### Payment
- **Status**: ✅ Enhanced migration
- **Changes**:
  - Added more payment methods
  - Added gateway integration
  - Added multi-currency support
  - Added authorization code
  - Added gateway response storage

#### Transaction
- **Status**: ✅ Enhanced migration
- **Changes**:
  - Added more transaction types
  - Added balance tracking
  - Added multi-entity links (payment, invoice, order)

---

### From freight/models/support.py → bfg2_support

#### SupportTicket
- **Status**: ✅ Enhanced migration
- **Changes**:
  - Added ticket number field
  - Added more status choices
  - Added channel tracking
  - Added SLA tracking
  - Added assignment fields
  - Added satisfaction rating
  - Added order and consignment links

#### SupportTicketMessage
- **Status**: ✅ Enhanced migration
- **Changes**:
  - Added message type
  - Added attachments as JSON
  - Added email tracking

---

## New Models (Not Migrated)

### bfg2_web (All New)
- Page
- Post
- Category
- Tag
- Menu
- MenuItem
- Translation
- Language
- Media

### bfg2_shop (All New)
- ProductCategory
- Product
- ProductVariant
- ProductImage
- Cart
- CartItem
- OrderStatus
- Order
- OrderItem
- ProductReview

### bfg2_delivery (New Models)
- Carrier
- DeliveryZone
- PackageItem (was in freight but enhanced)
- ConsignmentItem (was in freight but enhanced)

### bfg2_promo (New Models)
- DiscountRule
- ReferralProgram
- Referral
- Channel
- ChannelLink
- LinkClick
- AffiliatePartner
- CampaignAnalytics

### bfg2_finance (New Models)
- InvoiceItem
- PaymentGateway
- Refund
- TaxRate
- Currency
- ExchangeRate
- PaymentMethod

### bfg2_support (New Models)
- TicketCategory
- TicketPriority
- TicketAttachment
- SupportTeam
- TicketAssignment
- SLA
- KnowledgeCategory
- KnowledgeBase
- TicketTemplate
- TicketTag

---

## Migration Strategy

### Phase 1: Preparation
1. ✅ Review all existing models
2. ✅ Document migration mapping
3. ✅ Create BFG2 module specifications
4. ⏳ Get user approval

### Phase 2: Setup
1. Create BFG2 package structure
2. Set up common infrastructure
3. Create base models and utilities
4. Set up multi-workspace framework

### Phase 3: Model Creation
1. Create all new models in BFG2 modules
2. Maintain backward compatibility where possible
3. Add enhancements and new fields
4. Create migrations

### Phase 4: Data Migration
1. Create migration scripts for each model
2. Map old fields to new fields
3. Preserve all existing data
4. Verify data integrity

### Phase 5: Testing
1. Unit tests for all models
2. Integration tests
3. Data migration testing on copy of production data
4. Performance testing

### Phase 6: Deployment
1. Deploy BFG2 as separate package
2. Install in current project
3. Run migrations
4. Gradual cutover from freight to bfg2

---

## Breaking Changes & Considerations

> [!WARNING]
> **Database Changes Required**
> The migration will require database schema changes. Existing data will need to be migrated using Django data migrations.

> [!IMPORTANT]
> **API Compatibility**
> New API endpoints will be created. Old freight APIs should remain for backward compatibility during transition period.

> [!CAUTION]
> **Foreign Key Changes**
> Some models will have new relationships. Carefully plan foreign key migrations to avoid data loss.

---

## Benefits of Migration

### 1. **Modularity**
- Independent modules can be used separately
- Clear boundaries between functionality
- Easier testing and maintenance

### 2. **Reusability**
- BFG2 can be used in other projects
- Standardized e-commerce and logistics solution
- Reduced development time for future projects

### 3. **Enhanced Features**
- Modern payment gateways
- Comprehensive promotion system
- Advanced support ticketing
- Multi-language CMS

### 4. **Scalability**
- Better organized codebase
- Easier to add new features
- Optimized for multi-workspace usage

### 5. **Maintainability**
- Clearer code organization
- Better documentation
- Standardized patterns

---

## Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| User Review & Approval | 1-2 days | None |
| Package Setup | 2-3 days | Approval |
| Common Infrastructure | 3-5 days | Package Setup |
| Module Implementation | 15-20 days | Common Infrastructure |
| Data Migration Scripts | 5-7 days | Module Implementation |
| Testing | 7-10 days | Data Migration |
| Documentation | 3-5 days | Parallel with Development |
| Deployment | 2-3 days | Testing Complete |

**Total Estimated Time**: 6-8 weeks

---

## Next Steps

1. ✅ Review architecture documentation (`docs/bfg2/00-architecture.md`)
2. ✅ Review module specifications:
   - `docs/bfg2/01-bfg2_web.md`
   - `docs/bfg2/02-bfg2_shop.md`
   - `docs/bfg2/03-bfg2_delivery.md`
   - `docs/bfg2/04-bfg2_promo.md`
   - `docs/bfg2/05-bfg2_finance.md`
   - `docs/bfg2/06-bfg2_support.md`
3. ⏳ Review this migration mapping
4. ⏳ Approve implementation plan
5. ⏳ Decide on:
   - Module naming conventions
   - Multi-workspace requirements
   - Timeline and priorities
   - Which modules to implement first
