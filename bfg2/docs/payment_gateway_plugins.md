# Payment Gateway 插件系统

## 概述

Payment Gateway 采用插件化架构，每个支付网关作为独立的插件实现。这种设计使得：

- ✅ **易于扩展**: 添加新的支付网关只需创建新的插件目录
- ✅ **代码隔离**: 每个网关的实现相互独立，互不干扰
- ✅ **统一接口**: 所有网关实现相同的接口，便于统一管理
- ✅ **自动发现**: 系统自动发现并加载所有可用插件

## 目录结构

```
bfg/finance/gateways/
├── __init__.py              # 插件系统导出
├── base.py                   # 基础抽象类
├── loader.py                 # 插件加载器
├── stripe/                   # Stripe 插件
│   ├── __init__.py
│   └── plugin.py            # Stripe 插件实现
├── paypal/                   # PayPal 插件 (示例)
│   ├── __init__.py
│   └── plugin.py
└── alipay/                   # 支付宝插件 (示例)
    ├── __init__.py
    └── plugin.py
```

## 创建新插件

### 1. 创建插件目录

在 `bfg/finance/gateways/` 下创建新目录，例如 `paypal/`:

```bash
mkdir -p bfg/finance/gateways/paypal
```

### 2. 创建插件文件

创建 `plugin.py` 文件，继承 `BasePaymentGateway`:

```python
# bfg/finance/gateways/paypal/plugin.py
from bfg.finance.gateways.base import BasePaymentGateway
from typing import Dict, Any, Optional
from decimal import Decimal
from bfg.finance.models import PaymentMethod, Payment, Currency
from bfg.common.models import Customer


class PayPalGateway(BasePaymentGateway):
    """
    PayPal payment gateway plugin
    """
    
    gateway_type = 'paypal'
    display_name = 'PayPal'
    supported_methods = ['paypal', 'card']
    
    def _validate_config(self):
        """Validate PayPal configuration"""
        client_id = self.config.get('client_id')
        client_secret = self.config.get('client_secret')
        
        if not client_id or not client_secret:
            raise ValueError("PayPal client_id and client_secret required")
    
    def get_config_schema(self) -> Dict[str, Any]:
        """Get PayPal configuration schema"""
        return {
            'client_id': {
                'type': 'string',
                'required': True,
                'description': 'PayPal Client ID',
                'sensitive': False,
            },
            'client_secret': {
                'type': 'string',
                'required': True,
                'description': 'PayPal Client Secret',
                'sensitive': True,
            },
        }
    
    def create_payment_method(self, customer, payment_method_data):
        """Create PayPal payment method"""
        # Implement PayPal payment method creation
        pass
    
    def save_payment_method(self, customer, gateway_payment_method_id, payment_method_data=None):
        """Save PayPal payment method"""
        # Implement saving to BFG PaymentMethod model
        pass
    
    def create_payment_intent(self, customer, amount, currency, payment_method_id=None, order_id=None, metadata=None):
        """Create PayPal payment order"""
        # Implement PayPal payment order creation
        pass
    
    def confirm_payment(self, payment, payment_intent_id=None, payment_details=None):
        """Confirm PayPal payment"""
        # Implement PayPal payment confirmation
        pass
    
    def handle_webhook(self, event_type, payload):
        """Handle PayPal webhook events"""
        # Implement PayPal webhook handling
        pass
```

### 3. 创建 `__init__.py`

```python
# bfg/finance/gateways/paypal/__init__.py
from .plugin import PayPalGateway

__all__ = ['PayPalGateway']
```

### 4. 系统自动发现

插件系统会自动发现并加载插件，无需额外配置。

## 插件接口

所有插件必须实现 `BasePaymentGateway` 中定义的抽象方法：

### 必需方法

1. **`create_payment_method()`** - 在网关中创建支付方式
2. **`save_payment_method()`** - 保存到 BFG PaymentMethod 模型
3. **`create_payment_intent()`** - 创建支付意图
4. **`confirm_payment()`** - 确认/处理支付
5. **`handle_webhook()`** - 处理 webhook 事件

### 可选方法

1. **`delete_payment_method()`** - 删除支付方式（默认仅删除数据库记录）
2. **`create_refund()`** - 创建退款（默认不支持）
3. **`cancel_payment()`** - 取消支付（默认不支持）
4. **`verify_webhook()`** - 验证 webhook 签名（默认总是返回 True）
5. **`get_or_create_customer()`** - 获取或创建网关客户（默认返回客户 ID）

### 配置方法

1. **`get_config_schema()`** - 返回配置字段定义
2. **`get_frontend_config()`** - 返回前端配置（安全暴露）
3. **`get_supported_currencies()`** - 返回支持的货币列表
4. **`get_supported_countries()`** - 返回支持的国家列表

## 使用插件

### 在代码中使用

```python
from bfg.finance.gateways.loader import get_gateway_plugin

# 获取插件实例
gateway = PaymentGateway.objects.get(id=1)
plugin = get_gateway_plugin(gateway)

if plugin:
    # 创建支付意图
    payment_intent = plugin.create_payment_intent(
        customer=customer,
        amount=Decimal('100.00'),
        currency=currency,
        payment_method_id=payment_method.gateway_token
    )
    
    # 确认支付
    result = plugin.confirm_payment(payment, payment_intent_id=payment_intent['payment_intent_id'])
```

### 列出所有可用插件

```python
from bfg.finance.gateways.loader import GatewayLoader

plugins = GatewayLoader.list_available_plugins()
# {'stripe': 'Stripe', 'paypal': 'PayPal', ...}

# 获取插件信息
info = GatewayLoader.get_plugin_info('stripe')
# {
#     'gateway_type': 'stripe',
#     'display_name': 'Stripe',
#     'supported_methods': ['card'],
#     'config_schema': {...}
# }
```

## 插件配置

每个插件在 PaymentGateway 的 `config` 字段中存储配置：

```python
gateway = PaymentGateway.objects.create(
    workspace=workspace,
    name='Stripe Gateway',
    gateway_type='stripe',
    config={
        'secret_key': 'sk_test_...',
        'publishable_key': 'pk_test_...',
        'webhook_secret': 'whsec_...',
    },
    is_active=True,
    is_test_mode=True
)
```

## 现有插件

### Stripe Plugin

位置: `bfg/finance/gateways/stripe/plugin.py`

功能:
- ✅ 支付方式管理（通过 Stripe Elements）
- ✅ PaymentIntent 创建和确认
- ✅ 3D Secure 支持
- ✅ Webhook 处理
- ✅ 退款支持

配置:
```json
{
  "secret_key": "sk_test_...",
  "publishable_key": "pk_test_...",
  "webhook_secret": "whsec_..."
}
```

## 最佳实践

1. **错误处理**: 所有方法都应该有适当的错误处理
2. **日志记录**: 记录重要的操作和错误
3. **配置验证**: 在 `_validate_config()` 中验证所有必需的配置
4. **文档**: 为每个插件编写清晰的文档
5. **测试**: 为每个插件编写单元测试和集成测试

## 迁移指南

### 从旧代码迁移

如果你有旧的网关实现代码（如 `StripeService`），可以按以下步骤迁移：

1. 创建插件目录和文件
2. 将旧代码逻辑移到插件类中
3. 实现所有必需的方法
4. 测试插件功能
5. 删除旧代码

### 示例：迁移 Stripe

旧代码在 `bfg/finance/services/stripe_service.py`，已迁移到 `bfg/finance/gateways/stripe/plugin.py`。

## 故障排除

### 插件未加载

- 检查插件目录是否存在
- 检查 `plugin.py` 文件是否存在
- 检查插件类是否正确继承 `BasePaymentGateway`
- 检查 `gateway_type` 是否正确设置
- 查看日志中的错误信息

### 配置错误

- 检查 `config` 字段是否包含所有必需项
- 检查 `_validate_config()` 方法是否正确实现
- 查看配置 schema 定义

## 扩展功能

### 添加自定义方法

插件可以添加自定义方法，但不应影响核心接口：

```python
class CustomGateway(BasePaymentGateway):
    def custom_method(self):
        """Custom functionality specific to this gateway"""
        pass
```

### 事件处理

插件可以触发自定义事件：

```python
from bfg.core.events import global_dispatcher

def handle_webhook(self, event_type, payload):
    # Process webhook
    global_dispatcher.dispatch('custom.gateway.event', {'data': ...})
```

## 参考

- [BasePaymentGateway API 文档](base.py)
- [插件加载器文档](loader.py)
- [Stripe 插件示例](stripe/plugin.py)

