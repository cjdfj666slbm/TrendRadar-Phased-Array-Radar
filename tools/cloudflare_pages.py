"""把 HTML 报告发布到 Cloudflare Pages 的小工具。

只依赖标准库（urllib），不引入额外依赖，便于跟随 GUI 一起打包。
使用 Cloudflare Pages 的 Direct Upload API：
  1. 取上传凭证（JWT）
  2. 上传文件内容，拿到文件 hash
  3. 创建部署并关联文件
文档：https://developers.cloudflare.com/api/resources/pages/
"""

from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareError(RuntimeError):
    """Cloudflare 接口返回错误。"""


def _request(
    method: str,
    url: str,
    token: str,
    *,
    data: bytes | None = None,
    content_type: str = "application/json",
    timeout: int = 120,
) -> Any:
    """发送请求并解析 Cloudflare 的统一响应结构。"""
    headers = {"Authorization": f"Bearer {token}"}
    body = data
    if data is not None and content_type == "application/json":
        headers["Content-Type"] = "application/json"
    elif data is not None:
        headers["Content-Type"] = content_type

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read(2000).decode("utf-8", "replace")
        except Exception:
            pass
        raise CloudflareError(f"HTTP {error.code}: {_summarize(detail)}") from error
    except urllib.error.URLError as error:
        raise CloudflareError(f"网络错误: {error.reason}") from error

    if not payload.strip():
        return {}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as error:
        raise CloudflareError(f"返回内容不是 JSON: {payload[:200]}") from error

    if isinstance(parsed, dict) and parsed.get("success") is False:
        errors = parsed.get("errors") or []
        raise CloudflareError(_format_errors(errors))
    return parsed


def _summarize(raw: str) -> str:
    """把 Cloudflare 的错误体压缩成一句话。"""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:300]
    if isinstance(parsed, dict):
        errors = parsed.get("errors")
        if errors:
            return _format_errors(errors)
    return raw[:300]


def _format_errors(errors: list[dict[str, Any]]) -> str:
    parts = []
    for item in errors or []:
        if isinstance(item, dict):
            code = item.get("code", "")
            message = item.get("message", "")
            parts.append(f"[{code}] {message}".strip())
        else:
            parts.append(str(item))
    return "; ".join(parts) or "未知错误"


def verify_credentials(account_id: str, token: str, project_name: str) -> dict[str, Any]:
    """校验 Account ID / Token / 项目名是否可用，返回项目信息。"""
    account_id = (account_id or "").strip()
    token = (token or "").strip()
    project_name = (project_name or "").strip()
    if not account_id:
        raise CloudflareError("缺少 Account ID")
    if not token:
        raise CloudflareError("缺少 API Token")
    if not project_name:
        raise CloudflareError("缺少项目名")

    url = f"{API_BASE}/accounts/{account_id}/pages/projects/{project_name}"
    result = _request("GET", url, token, timeout=30)
    project = result.get("result") if isinstance(result, dict) else None
    if not isinstance(project, dict):
        raise CloudflareError("项目不存在或无权访问，请检查项目名")
    return {
        "name": project.get("name", project_name),
        "subdomain": project.get("subdomain", ""),
        "production_url": (project.get("latest_deployment") or {}).get("url", ""),
    }


def publish_html(
    account_id: str,
    token: str,
    project_name: str,
    html_path: Path,
    *,
    remote_name: str = "index.html",
) -> str:
    """把本地 HTML 发布到 Pages 项目根目录，返回部署 URL。"""
    account_id = (account_id or "").strip()
    token = (token or "").strip()
    project_name = (project_name or "").strip()
    html_path = Path(html_path)
    if not html_path.is_file():
        raise CloudflareError(f"报告文件不存在: {html_path}")

    content = html_path.read_bytes()
    mime = mimetypes.guess_type(remote_name)[0] or "text/html"
    content_b64 = __import__("base64").b64encode(content).decode("ascii")

    # 1. 获取上传 JWT
    jwt_url = f"{API_BASE}/accounts/{account_id}/pages/projects/{project_name}/upload-token"
    jwt_result = _request("GET", jwt_url, token, timeout=30)
    jwt = (jwt_result.get("result") or {}).get("jwt") if isinstance(jwt_result, dict) else None
    if not jwt:
        raise CloudflareError("未能获取上传凭证（upload-token 返回为空）")

    # 2. 上传文件内容
    files_url = f"{API_BASE}/pages/assets/upload"
    manifest = [{"key": remote_name, "value": content_b64, "metadata": {"content_type": mime}, "base64": True}]
    _request(
        "POST",
        files_url,
        jwt,
        data=json.dumps(manifest).encode("utf-8"),
        content_type="application/json",
    )

    # 3. 触发部署，复用已上传的文件
    deploy_url = f"{API_BASE}/accounts/{account_id}/pages/projects/{project_name}/deployments"
    deploy_payload = {"files": {remote_name: content_b64}}
    result = _request(
        "POST",
        deploy_url,
        token,
        data=json.dumps(deploy_payload).encode("utf-8"),
        content_type="application/json",
    )
    deployment = result.get("result") if isinstance(result, dict) else None
    url = ""
    if isinstance(deployment, dict):
        url = deployment.get("url", "") or ""
        if not url:
            latest = deployment.get("latest_deployment") or {}
            url = latest.get("url", "") if isinstance(latest, dict) else ""
    return url or f"https://{project_name}.pages.dev"
