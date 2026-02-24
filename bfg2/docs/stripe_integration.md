# Stripe 支付集成指南

本指南说明如何使用 Stripe 完成支付方式添加和付款功能。

## 1. 安装依赖

首先安装 Stripe Python SDK:

```bash
pip install stripe
```

将 `stripe` 添加到 `requirements.txt`:

```txt
stripe>=7.0.0
```

## 2. 配置 Stripe Gateway

在后台管理中创建 Stripe PaymentGateway，配置如下：

```json
{
  "secret_key": "sk_test_...",  // Stripe Secret Key
  "publishable_key": "pk_test_...",  // Stripe Publishable Key (前端使用)
  "webhook_secret": "whsec_..."  // Webhook Secret (用于验证 webhook)
}
```

**重要提示：**
- Test Mode: 使用 `sk_test_...` 和 `pk_test_...`
- Live Mode: 使用 `sk_live_...` 和 `pk_live_...`
- Webhook Secret 需要在 Stripe Dashboard 中配置 webhook 后获取

## 3. 前端集成 (Stripe Elements)

### 3.1 安装 Stripe.js

```html
<script src="https://js.stripe.com/v3/"></script>
```

或使用 npm:

```bash
npm install @stripe/stripe-js
```

### 3.2 初始化 Stripe

```javascript
import { loadStripe } from '@stripe/stripe-js';

// 从你的后端 API 获取 publishable_key
const stripePromise = loadStripe('pk_test_...');
```

## 4. 添加支付方式

### 4.1 使用 Stripe Elements 收集卡信息

```javascript
import { CardElement, useStripe, useElements } from '@stripe/react-stripe-js';

function PaymentMethodForm() {
  const stripe = useStripe();
  const elements = useElements();
  
  const handleSubmit = async (event) => {
    event.preventDefault();
    
    if (!stripe || !elements) {
      return;
    }
    
    // 创建 PaymentMethod
    const { error, paymentMethod } = await stripe.createPaymentMethod({
      type: 'card',
      card: elements.getElement(CardElement),
      billing_details: {
        name: 'Customer Name',
      },
    });
    
    if (error) {
      console.error(error);
      return;
    }
    
    // 发送到后端保存
    const response = await fetch('/api/v1/me/payment-methods/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        gateway: gatewayId,  // Stripe Gateway ID
        stripe_payment_method_data: {
          payment_method_id: paymentMethod.id  // PaymentMethod ID from Stripe
        },
        is_default: true
      })
    });
    
    const savedPaymentMethod = await response.json();
    console.log('Payment method saved:', savedPaymentMethod);
  };
  
  return (
    <form onSubmit={handleSubmit}>
      <CardElement />
      <button type="submit" disabled={!stripe}>
        Save Card
      </button>
    </form>
  );
}
```

### 4.2 API 请求示例

**POST /api/v1/me/payment-methods/**

```json
{
  "gateway": 1,
  "stripe_payment_method_data": {
    "payment_method_id": "pm_1234567890abcdef"
  },
  "billing_address_id": 1,
  "is_default": true
}
```

**响应:**

```json
{
  "id": 1,
  "gateway": 1,
  "gateway_name": "Stripe",
  "method_type": "card",
  "card_brand": "visa",
  "card_last4": "4242",
  "card_exp_month": 12,
  "card_exp_year": 2025,
  "display_info": "VISA •••• 4242",
  "is_default": true,
  "is_active": true
}
```

## 5. 创建支付意图 (Payment Intent)

### 5.1 API 调用

**POST /api/store/payments/intent/**

```json
{
  "order_id": 123,
  "gateway_id": 1,
  "payment_method_id": 1  // 可选，如果使用保存的支付方式
}
```

**响应:**

```json
{
  "payment_id": 456,
  "payment_number": "PAY-20240101-12345",
  "amount": "100.00",
  "currency": "USD",
  "status": "pending",
  "gateway_payload": {
    "client_secret": "pi_1234567890_secret_...",
    "payment_intent_id": "pi_1234567890",
    "status": "requires_payment_method"
  }
}
```

### 5.2 前端确认支付

```javascript
async function confirmPayment(clientSecret, paymentMethodId = null) {
  const stripe = await stripePromise;
  
  const result = await stripe.confirmCardPayment(clientSecret, {
    payment_method: paymentMethodId || {
      card: cardElement,
      billing_details: {
        name: 'Customer Name',
      },
    },
  });
  
  if (result.error) {
    // 处理错误
    console.error(result.error.message);
  } else {
    // 支付成功
    if (result.paymentIntent.status === 'succeeded') {
      console.log('Payment succeeded!');
      // 刷新订单状态
    }
  }
}
```

### 5.3 处理 3D Secure

如果支付需要 3D Secure 验证：

```javascript
const result = await stripe.confirmCardPayment(clientSecret, {
  payment_method: paymentMethodId,
  return_url: `${window.location.origin}/payment/return`,
});

if (result.error) {
  if (result.error.type === 'card_error') {
    console.error(result.error.message);
  }
} else {
  if (result.paymentIntent.status === 'requires_action') {
    // 重定向到 3D Secure 验证页面
    // Stripe 会自动处理
  }
}
```

## 6. 处理 Webhook

### 6.1 配置 Stripe Webhook

在 Stripe Dashboard 中配置 webhook endpoint:

```
https://yourdomain.com/api/store/payments/callback/stripe
```

需要监听的事件：
- `payment_intent.succeeded`
- `payment_intent.payment_failed`
- `payment_method.attached`

### 6.2 Webhook 处理

Webhook 会自动更新支付状态：

```python
# 已自动处理在 StorefrontPaymentViewSet._handle_stripe_webhook
# 当 payment_intent.succeeded 时，会：
# - 更新 Payment.status = 'completed'
# - 更新 Order.payment_status = 'paid'
# - 更新 Invoice.status = 'paid' (如果有)
```

## 7. 完整支付流程示例

### 7.1 使用新卡支付

```javascript
// 1. 创建订单
const order = await createOrder(orderData);

// 2. 创建支付意图
const intentResponse = await fetch('/api/store/payments/intent/', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({
    order_id: order.id,
    gateway_id: stripeGatewayId
  })
});

const { gateway_payload } = await intentResponse.json();

// 3. 使用 Stripe Elements 确认支付
const stripe = await stripePromise;
const cardElement = elements.getElement(CardElement);

const { error, paymentIntent } = await stripe.confirmCardPayment(
  gateway_payload.client_secret,
  {
    payment_method: {
      card: cardElement,
      billing_details: {
        name: customerName,
      },
    },
  }
);

if (error) {
  console.error('Payment failed:', error.message);
} else if (paymentIntent.status === 'succeeded') {
  console.log('Payment successful!');
  // 刷新订单状态
}
```

### 7.2 使用保存的支付方式

```javascript
// 1. 获取保存的支付方式
const paymentMethods = await fetch('/api/v1/me/payment-methods/').then(r => r.json());

// 2. 创建支付意图，指定 payment_method_id
const intentResponse = await fetch('/api/store/payments/intent/', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({
    order_id: order.id,
    gateway_id: stripeGatewayId,
    payment_method_id: paymentMethods[0].id  // 使用保存的支付方式
  })
});

const { gateway_payload } = await intentResponse.json();

// 3. 确认支付（可能不需要额外确认，取决于 PaymentIntent 状态）
const stripe = await stripePromise;
const { error, paymentIntent } = await stripe.confirmCardPayment(
  gateway_payload.client_secret
);

if (paymentIntent.status === 'succeeded') {
  console.log('Payment successful!');
}
```

## 8. 错误处理

### 常见错误

1. **Card declined**
   ```javascript
   if (error.code === 'card_declined') {
     // 卡被拒绝
   }
   ```

2. **Insufficient funds**
   ```javascript
   if (error.code === 'insufficient_funds') {
     // 余额不足
   }
   ```

3. **3D Secure required**
   ```javascript
   if (result.paymentIntent.status === 'requires_action') {
     // 需要 3D Secure 验证
   }
   ```

## 9. 测试

### 测试卡号

Stripe 提供以下测试卡号：

- **成功:** `4242 4242 4242 4242`
- **需要 3D Secure:** `4000 0027 6000 3184`
- **被拒绝:** `4000 0000 0000 0002`
- **余额不足:** `4000 0000 0000 9995`

更多测试卡号: https://stripe.com/docs/testing

## 10. 安全注意事项

1. **永远不要在前端使用 Secret Key**
   - Secret Key 只能在后端使用
   - Publishable Key 可以安全地暴露在前端

2. **验证 Webhook 签名**
   - 代码已自动处理 webhook 签名验证
   - 确保配置了正确的 `webhook_secret`

3. **PCI 合规**
   - 使用 Stripe Elements 可以避免 PCI 合规问题
   - 永远不要直接收集或存储完整的卡号

4. **HTTPS**
   - 生产环境必须使用 HTTPS
   - Stripe 不允许在 HTTP 上处理支付

## 11. 参考链接

- [Stripe API 文档](https://stripe.com/docs/api)
- [Stripe Elements](https://stripe.com/docs/stripe-js/react)
- [Stripe Webhooks](https://stripe.com/docs/webhooks)
- [Stripe Testing](https://stripe.com/docs/testing)

