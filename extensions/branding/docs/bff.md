# Brand Portal BFF 接入说明

Brand Portal API 是给品牌网站服务端使用的 HTTP 接口。浏览器只访问品牌网站自己的 Next.js 页面和 Route Handler，不直接访问 BFG API，也不得接触 Portal API secret。

## 服务端配置

在 Next.js 部署环境中设置：

```dotenv
BFG_API_URL=https://api.example.test
BFG_PORTAL_API_KEY=xxxxxxxx
BFG_PORTAL_API_SECRET=xxxxxxxx
```

这些变量不能使用 `NEXT_PUBLIC_` 前缀。建议在每个 Brand Workspace 下创建独立 API key；轮换时先部署新 key，再停用旧 key。

参考 client 位于 [`docs/examples/brand-portal-bff-client.ts`](../examples/brand-portal-bff-client.ts)。它导入 `server-only`，只接受相对 API path，并只在 BFF 到 BFG 的请求中加入密钥。

## v1 接口

所有接口都要求 `X-Api-Key` 与 `X-Api-Secret`：

| 方法和路径 | 用途 |
| --- | --- |
| `GET /api/v1/brand_portal/v1/config/` | 读取品牌公开配置和是否开放注册。 |
| `GET /api/v1/brand_portal/v1/cms/pages/{slug}/` | 读取已发布页面的 rendered blocks。 |
| `GET /api/v1/brand_portal/v1/cms/posts/{slug}/` | 读取已经到发布时间的已发布文章。 |
| `GET /api/v1/brand_portal/v1/cms/menus/{slug}/` | 读取 active 菜单，并移除 inactive 或指向草稿内容的菜单项。 |
| `POST /api/v1/brand_portal/v1/auth/register/` | 创建全局账号并启动既有邮箱验证流程，不提前创建 Workspace。 |
| `POST /api/v1/brand_portal/v1/auth/finalize/` | 验证邮箱 proof 后，原子创建 Workspace、owner/admin、基础数据、Extension 和一次性进入码。 |

CMS 接口接受可选的 `language` query parameter。未提供时使用 Portal Profile 的默认语言，再按 BFG CMS 的语言回退规则读取内容。

请求不得包含 `workspace`、`workspace_id`、`portal_workspace_id` 或 `provisioning_extensions`。Brand Workspace 始终由 API key 决定，出现这些字段时返回 `portal_selector_forbidden`。

## Next.js Route Handler

浏览器可以访问同域 `/api/content/page/about`，由 Route Handler 调用 BFG：

```ts
import { NextResponse } from 'next/server';
import { getPortalPage, PortalApiError } from '@/lib/brand-portal';

export async function GET() {
  try {
    return NextResponse.json(await getPortalPage('about', 'en-nz'));
  } catch (error) {
    if (error instanceof PortalApiError) {
      return NextResponse.json(
        { code: error.code, requestId: error.requestId },
        { status: error.status },
      );
    }
    throw error;
  }
}
```

不要把上游响应头、API secret 或上游错误 detail 原样返回浏览器。用户可见错误只需返回稳定 code 和 request ID。

## 错误与 request ID

API 成功和已规范化的错误响应都会带 `X-Request-ID`。BFF 可以传入最多 64 字符、只包含字母数字、`.`、`_`、`-` 的 request ID；否则服务端自动生成 UUID。

错误 body：

```json
{
  "code": "content_not_found",
  "detail": "Published content was not found.",
  "request_id": "6c075a30-aed2-44fb-a0f2-50eb3c4b08a1"
}
```

稳定错误码包括：

- `api_credentials_required` / `invalid_api_credentials`
- `portal_unavailable`
- `portal_not_configured`
- `portal_selector_forbidden`
- `invalid_language`
- `content_not_found`

应用日志不得记录 `X-Api-Secret`、用户密码、JWT、邮箱验证 token 或 SSO code。request ID 可以安全记录，用于关联 Next.js 与 BFG 日志。

## 注册和创建 Workspace

`register` 接受：

```json
{
  "email": "owner@example.com",
  "password": "a-strong-password",
  "password_confirm": "a-strong-password",
  "first_name": "Casey",
  "last_name": "Owner"
}
```

已有 Email 返回 `email_already_registered`，品牌站应引导用户登录。该接口按 Portal API key 和来源 IP 限流；不会接受 `store_name` 来绕过 Portal provisioning。

邮箱验证完成后，`finalize` 接受：

```json
{
  "onboarding_token": "<verify-email 返回的短期签名 token>",
  "workspace_name": "Casey Store",
  "admin_name": "Casey Owner"
}
```

请求必须携带 `Idempotency-Key`。同一个 Portal Workspace 内，相同 key 只创建一次；失败重试仍使用首次请求时保存的 workspace 名称、管理员名称和 Portal Profile 快照。请求体不能选择目标 Extension、Portal Workspace、domain、next 或任意 absolute redirect URL。

成功响应包含 Workspace 的 UUID、名称、slug、平台访问地址、实际装载的 Extension key、短期一次性 `redirect_url` 和过期时间。进入码固定绑定新 Workspace、注册用户、该 Workspace 的平台域名和 `/admin`。

业务 Workspace 的系统域名由 Brand Workspace 所属 cluster 的 `frontend_base_url` 派生。例如 cluster 前端地址为 `https://app.example.com`，新 Workspace slug 为 `casey-store`，则平台访问地址为 `https://casey-store.app.example.com`。Brand Workspace 未配置可用 cluster 前端地址时，创建整体回滚并返回 `workspace_domain_unavailable`。

数据库驱动的品牌回调域名仍不在当前范围；这里使用的是新业务 Workspace 的平台访问域名，不是 Surlex/Idlevo 的邮箱、密码重置或 OAuth 最终回调域名。

写接口的稳定错误码还包括：

- `registration_disabled`
- `invalid_registration` / `verification_email_failed`
- `onboarding_proof_required`
- `invalid_idempotency_key` / `idempotency_conflict`
- `workspace_limit_reached`
- `extension_activation_failed` / `workspace_domain_unavailable` / `provisioning_failed`
- `rate_limited`

Next.js BFF 调用示例已经加入：

```text
registerPortalUser(input)
finalizePortalWorkspace(input, idempotencyKey)
```

登录和一次性 SSO 在真实品牌站集成阶段实现，路径预留为：

```text
POST /api/v1/brand_portal/v1/auth/login/
POST /api/v1/brand_portal/v1/auth/sso/start/
```

数据库驱动的品牌回调域名不属于当前版本。最终浏览器回跳地址由每个 Next.js 部署的服务端静态配置决定。

## 平台配置界面

平台管理员在 Workspace 的 Extension 页面激活私有 `brand_portal` 后，可以直接配置注册开关、默认功能包、国家、币种、语言、主题和方案，并查看已验证域名及最近 20 条开通记录。普通 Workspace owner 不加载该面板，也无权访问其 API。

配置界面使用以下平台管理员接口：

```text
GET   /api/v1/brand_portal/v1/console/workspaces/{workspace_id}/
PATCH /api/v1/brand_portal/v1/console/workspaces/{workspace_id}/
```

这些接口是跨 Workspace 的平台控制面能力，不依赖管理员 JWT 当前绑定的 Workspace。Profile 保存后会在数据库 transaction commit 时使缓存失效，新增品牌和修改默认功能包不需要调整 CORS，也不需要重启 BFG。
