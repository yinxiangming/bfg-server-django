# 库存系统模型关系说明

## 概述

BFG2 的库存系统采用三层架构：
1. **ProductVariant** - 变体级别的总库存（汇总值）
2. **VariantInventory** - 仓库级别的库存明细（真实数据源）
3. **ProductBatch** - 批次级别的库存追踪（可选，用于批次管理）

## 模型关系图

```
Product (产品)
  └── ProductVariant (变体) [stock_quantity: 汇总值]
        ├── VariantInventory (仓库库存) [quantity, reserved] ← 真实数据源
        │     └── Warehouse (仓库)
        │
        └── ProductBatch (批次) [quantity, reserved] ← 可选，用于批次追踪
              └── Warehouse (仓库)
                    └── BatchMovement (批次移动记录)
```

## 详细模型说明

### 1. Product (产品)
**位置**: `bfg/shop/models/product.py`

```python
class Product(models.Model):
    stock_quantity = models.IntegerField(default=0)  # 产品级别的总库存（通常不使用）
    track_inventory = models.BooleanField(default=True)  # 是否追踪库存
```

**说明**:
- `stock_quantity` 在 Product 级别通常不使用，因为库存是在 Variant 级别管理的
- `track_inventory` 标志是否启用库存追踪

---

### 2. ProductVariant (产品变体)
**位置**: `bfg/shop/models/product.py`

```python
class ProductVariant(models.Model):
    product = models.ForeignKey(Product, related_name='variants')
    stock_quantity = models.IntegerField(default=0)  # ⚠️ 汇总值，从 VariantInventory 同步
```

**关键点**:
- `stock_quantity` 是一个**汇总值**，不是真实数据源
- 它应该等于所有 `VariantInventory.quantity` 的总和
- 通过 `InventoryService` 自动同步更新

**关系**:
- `variant.inventory` → 所有 VariantInventory 记录（按仓库）
- `variant.batches` → 所有 ProductBatch 记录（如果启用批次管理）

---

### 3. VariantInventory (变体仓库库存) ⭐ **真实数据源**
**位置**: `bfg/shop/models/product.py`

```python
class VariantInventory(models.Model):
    variant = models.ForeignKey(ProductVariant, related_name='inventory')
    warehouse = models.ForeignKey('delivery.Warehouse', related_name='variant_inventory')
    
    quantity = models.IntegerField(default=0)      # 总数量
    reserved = models.IntegerField(default=0)    # 预留数量（已下单但未发货）
    
    @property
    def available(self):
        """可用数量 = 总数量 - 预留数量"""
        return self.quantity - self.reserved
```

**关键点**:
- **这是库存的真实数据源**
- 每个变体在每个仓库都有一个 VariantInventory 记录
- `quantity` 是总库存数量
- `reserved` 是已预留的数量（如订单已创建但未发货）
- `available` 是可用数量（可售数量）

**唯一约束**: `unique_together = ('variant', 'warehouse')`

**示例**:
```
Variant: "T-Shirt - Large"
├── VariantInventory @ Warehouse A: quantity=100, reserved=10, available=90
├── VariantInventory @ Warehouse B: quantity=50, reserved=5, available=45
└── ProductVariant.stock_quantity = 150 (自动同步)
```

---

### 4. ProductBatch (产品批次) - 可选
**位置**: `bfg/shop/models/batch.py`

```python
class ProductBatch(models.Model):
    workspace = models.ForeignKey('common.Workspace')
    variant = models.ForeignKey(ProductVariant, related_name='batches')
    warehouse = models.ForeignKey('delivery.Warehouse')
    
    batch_number = models.CharField()  # 批次号
    quantity = models.IntegerField(default=0)      # 批次数量
    reserved = models.IntegerField(default=0)      # 批次预留数量
    
    manufactured_date = models.DateField()  # 生产日期
    expiry_date = models.DateField(null=True)  # 过期日期
    quality_status = models.CharField()  # 质量状态
```

**关键点**:
- 这是**可选的**高级功能，需要启用 `ENABLE_BATCH_MANAGEMENT`
- 用于需要批次追踪的场景（如食品、药品）
- 支持 FIFO (先进先出) 库存管理
- 批次数量应该与 VariantInventory 的数量保持一致（但系统不强制）

**关系**:
- `batch.movements` → BatchMovement 记录（批次移动历史）

---

### 5. BatchMovement (批次移动记录)
**位置**: `bfg/shop/models/batch.py`

```python
class BatchMovement(models.Model):
    batch = models.ForeignKey(ProductBatch, related_name='movements')
    movement_type = models.CharField()  # 'in', 'out', 'transfer', 'adjustment', 'return'
    quantity = models.IntegerField()  # 正数表示增加，负数表示减少
    reason = models.CharField()
    order = models.ForeignKey('Order', null=True)  # 关联订单（如果有）
```

**用途**: 记录所有批次库存的移动历史，用于审计追踪

---

## 库存同步机制

### 自动同步流程

当 `VariantInventory` 发生变化时，需要同步更新 `ProductVariant.stock_quantity`：

```python
# 在 InventoryService 中
def adjust_stock(variant, warehouse, quantity_change):
    # 1. 更新 VariantInventory
    inventory.quantity = F('quantity') + quantity_change
    inventory.save()
    
    # 2. 同步更新 ProductVariant.stock_quantity
    total_quantity = VariantInventory.objects.filter(
        variant=variant
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    variant.stock_quantity = total_quantity
    variant.save()
```

### 同步时机

以下操作会自动触发同步：
1. `InventoryService.adjust_stock()` - 调整库存
2. `InventoryService.fulfill_reservation()` - 完成预留（发货）
3. 手动创建/更新 VariantInventory 后（需要手动调用同步）

---

## 库存计算逻辑

### 总库存 (Total Stock)
```
ProductVariant.stock_quantity = SUM(VariantInventory.quantity) 所有仓库
```

### 可用库存 (Available Stock)
```
VariantInventory.available = VariantInventory.quantity - VariantInventory.reserved

总可用库存 = SUM(VariantInventory.available) 所有仓库
```

### 预留库存 (Reserved Stock)
```
总预留库存 = SUM(VariantInventory.reserved) 所有仓库
```

---

## 数据流向

### 创建库存数据
```
1. 创建 ProductVariant
2. 创建 VariantInventory (按仓库)
   └── 设置 quantity 和 reserved
3. 同步 ProductVariant.stock_quantity
   └── 汇总所有 VariantInventory.quantity
4. (可选) 创建 ProductBatch
   └── 记录批次信息
```

### 库存变更流程
```
订单创建:
1. 检查 VariantInventory.available >= 订单数量
2. 增加 VariantInventory.reserved
3. (可选) 增加 ProductBatch.reserved
4. 不更新 quantity（库存还在）

订单发货:
1. 减少 VariantInventory.quantity
2. 减少 VariantInventory.reserved
3. (可选) 减少 ProductBatch.quantity 和 reserved
4. 同步 ProductVariant.stock_quantity
5. 创建 BatchMovement 记录（如果使用批次）
```

---

## 在 Storefront API 中的使用

### StorefrontProductVariantSerializer

```python
class StorefrontProductVariantSerializer:
    stock_quantity = IntegerField()  # 从 ProductVariant.stock_quantity 读取
    stock_available = SerializerMethodField()  # 计算: SUM(VariantInventory.available)
    stock_reserved = SerializerMethodField()  # 计算: SUM(VariantInventory.reserved)
    stock_by_warehouse = SerializerMethodField()  # 返回每个仓库的明细
```

**数据来源**:
- `stock_quantity`: 直接从 `ProductVariant.stock_quantity` 读取（汇总值）
- `stock_available`: 实时计算 `SUM(VariantInventory.quantity - VariantInventory.reserved)`
- `stock_reserved`: 实时计算 `SUM(VariantInventory.reserved)`
- `stock_by_warehouse`: 返回所有 `VariantInventory` 记录的详细信息

---

## 最佳实践

### ✅ 推荐做法

1. **始终通过 VariantInventory 管理库存**
   ```python
   # ✅ 正确
   inventory = VariantInventory.objects.get(variant=variant, warehouse=warehouse)
   inventory.quantity += 10
   inventory.save()
   # 然后同步 variant.stock_quantity
   ```

2. **使用 InventoryService 进行库存操作**
   ```python
   # ✅ 正确
   service = InventoryService(workspace=workspace)
   service.adjust_stock(variant, warehouse, quantity_change=10)
   # 自动同步 variant.stock_quantity
   ```

3. **查询可用库存时使用 VariantInventory**
   ```python
   # ✅ 正确
   available = VariantInventory.objects.filter(
       variant=variant
   ).aggregate(
       total=Sum(F('quantity') - F('reserved'))
   )['total']
   ```

### ❌ 避免的做法

1. **不要直接修改 ProductVariant.stock_quantity**
   ```python
   # ❌ 错误
   variant.stock_quantity = 100
   variant.save()
   # 这会导致数据不一致
   ```

2. **不要跳过 VariantInventory 直接操作**
   ```python
   # ❌ 错误
   variant.stock_quantity = 50
   # 应该通过 VariantInventory 操作
   ```

---

## 总结

| 模型 | 作用 | 数据性质 | 是否真实数据源 |
|------|------|----------|----------------|
| **ProductVariant.stock_quantity** | 变体总库存 | 汇总值 | ❌ 否（自动同步） |
| **VariantInventory.quantity** | 仓库库存 | 真实数据 | ✅ 是 |
| **VariantInventory.reserved** | 预留数量 | 真实数据 | ✅ 是 |
| **ProductBatch.quantity** | 批次数量 | 真实数据 | ✅ 是（可选） |

**核心原则**:
- **VariantInventory 是真实数据源**
- **ProductVariant.stock_quantity 是汇总值，自动同步**
- **ProductBatch 是可选的批次追踪功能**

