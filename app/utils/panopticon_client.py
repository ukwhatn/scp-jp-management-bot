"""Panopticon APIクライアント"""

import logging
from typing import Optional

import httpx
from pydantic import BaseModel


# レスポンススキーマ
class LinkStartResponse(BaseModel):
    link_url: str
    expires_at: str


class DiscordInfo(BaseModel):
    id: int
    discord_id: str
    username: str


class UserInfo(BaseModel):
    id: int
    name: str
    unix_name: str


class LinkRecheckResponse(BaseModel):
    linked: bool
    discord: DiscordInfo
    user: Optional[UserInfo] = None
    jp_member: bool


class BulkSiteMembership(BaseModel):
    id: int
    site_id: int
    site_unix_name: Optional[str] = None
    site_name: Optional[str] = None
    joined_at: str
    is_resigned: bool


class LinkedAccount(BaseModel):
    id: int
    user: UserInfo
    discord: DiscordInfo
    created_at: str
    site_memberships: list[BulkSiteMembership] = []


class BulkAccountInfo(BaseModel):
    discord_id: str
    linked: bool
    account: Optional[LinkedAccount] = None


class Site(BaseModel):
    id: int
    name: str
    unixName: str


class ApplicationUser(BaseModel):
    id: int
    name: str
    unixName: str
    avatarUrl: Optional[str] = None


class Application(BaseModel):
    id: int
    siteId: int
    userId: int
    acquiredAt: str
    text: str
    status: int
    declineReasonType: Optional[int] = None
    declineReasonDetail: Optional[str] = None
    reviewedAt: Optional[str] = None
    reviewedById: Optional[int] = None
    user: ApplicationUser
    reviewer: Optional[ApplicationUser] = None


class Pagination(BaseModel):
    total: int
    page: int
    perPage: int
    totalPages: int


class DeclineReasonType(BaseModel):
    id: int
    name: str
    description: str


class UserRole(BaseModel):
    id: int
    name: str


class UserDetail(BaseModel):
    id: int
    name: str
    unixName: str
    avatarUrl: Optional[str] = None
    isDeleted: bool


class UserWithPermissions(BaseModel):
    user: UserDetail
    roles: list[UserRole]
    permissions: list[str]


class SiteMembership(BaseModel):
    id: int
    siteId: int
    userId: int
    joinedAt: str
    isResigned: bool
    site: Optional[Site] = None


class PanopticonClient:
    """Panopticon APIクライアント"""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None
        self.logger = logging.getLogger("PanopticonClient")

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Origin": self.base_url,  # CSRF対策のためOriginヘッダーを追加
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ========== Link API ==========

    async def link_start(
        self,
        discord_id: str,
        username: str,
        discriminator: Optional[str] = None,
        avatar: Optional[str] = None,
    ) -> LinkStartResponse:
        """連携開始URL取得"""
        resp = await self.client.post(
            "/api/link/start",
            json={
                "discord_id": discord_id,
                "username": username,
                "discriminator": discriminator,
                "avatar": avatar,
            },
        )
        if not resp.is_success:
            self.logger.error(f"link_start API error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        return LinkStartResponse(**resp.json()["data"])

    async def link_recheck(
        self,
        discord_id: str,
        username: str,
        discriminator: Optional[str] = None,
        avatar: Optional[str] = None,
    ) -> LinkRecheckResponse:
        """連携情報再チェック（jp_member含む）"""
        resp = await self.client.post(
            "/api/link/recheck",
            json={
                "discord_id": discord_id,
                "username": username,
                "discriminator": discriminator,
                "avatar": avatar,
            },
        )
        if not resp.is_success:
            self.logger.error(f"link_recheck API error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        return LinkRecheckResponse(**resp.json()["data"])

    async def link_bulk(self, discord_ids: list[str]) -> list[BulkAccountInfo]:
        """複数Discord IDの連携情報取得"""
        resp = await self.client.post(
            "/api/link/bulk",
            json={
                "discord_ids": discord_ids,
            },
        )
        if not resp.is_success:
            self.logger.error(f"link_bulk API error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        return [BulkAccountInfo(**a) for a in resp.json()["data"]["accounts"]]

    # ========== Sites API ==========

    async def get_sites(self) -> list[Site]:
        """サイト一覧取得"""
        resp = await self.client.get("/api/sites")
        resp.raise_for_status()
        return [Site(**s) for s in resp.json()["data"]]

    async def get_applications(
        self,
        site_unix_name: str,
        status: Optional[int] = None,
        page: int = 1,
        per_page: int = 100,
    ) -> tuple[list[Application], Pagination]:
        """参加申請一覧取得"""
        params: dict = {"page": page, "per_page": per_page}
        if status is not None:
            params["status"] = status

        resp = await self.client.get(
            f"/api/sites/{site_unix_name}/applications",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        return (
            [Application(**a) for a in data["data"]],
            Pagination(**data["pagination"]),
        )

    async def approve_application(self, site_unix_name: str, app_id: int) -> None:
        """参加申請承認"""
        resp = await self.client.post(
            f"/api/sites/{site_unix_name}/applications/{app_id}/approve"
        )
        resp.raise_for_status()

    async def decline_application(
        self,
        site_unix_name: str,
        app_id: int,
        reason_type: int,
        reason_detail: Optional[str] = None,
    ) -> None:
        """参加申請拒否"""
        resp = await self.client.post(
            f"/api/sites/{site_unix_name}/applications/{app_id}/decline",
            json={"reasonType": reason_type, "reasonDetail": reason_detail},
        )
        resp.raise_for_status()

    async def get_decline_reason_types(self) -> list[DeclineReasonType]:
        """拒否理由タイプ一覧取得"""
        resp = await self.client.get("/api/sites/applications/decline-reason-types")
        resp.raise_for_status()
        return [DeclineReasonType(**t) for t in resp.json()["data"]]

    # ========== Users API ==========

    async def get_user(self, user_id: int) -> UserWithPermissions:
        """ユーザー情報取得（ロール・権限含む）"""
        resp = await self.client.get(f"/api/users/{user_id}")
        resp.raise_for_status()
        return UserWithPermissions(**resp.json()["data"])

    async def get_user_site_memberships(self, user_id: int) -> list[SiteMembership]:
        """ユーザーのサイトメンバーシップ取得"""
        resp = await self.client.get(f"/api/users/{user_id}/site-memberships")
        resp.raise_for_status()
        return [SiteMembership(**m) for m in resp.json()["data"]]

    # ========== Members API ==========

    async def change_privilege(
        self, site_unix_name: str, user_id: int, action: str
    ) -> None:
        """権限変更（action: "grant" または "revoke"）"""
        resp = await self.client.post(
            f"/api/sites/{site_unix_name}/members/{user_id}/privilege",
            json={"action": action},
        )
        resp.raise_for_status()

    # ========== ヘルパーメソッド ==========

    def has_admin_permission(self, permissions: list[str], site_unix_name: str) -> bool:
        """admin権限を持っているか確認"""
        return f"admin:{site_unix_name}" in permissions

    def has_moderate_permission(
        self, permissions: list[str], site_unix_name: str
    ) -> bool:
        """moderate以上の権限を持っているか確認"""
        return (
            f"admin:{site_unix_name}" in permissions
            or f"moderate:{site_unix_name}" in permissions
        )
