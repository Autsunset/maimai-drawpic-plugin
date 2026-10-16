from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from .atomic import write_json_atomically
from .settings import read_json_file
from ..concurrency import synchronized


QuotaPeriod = Literal["daily", "weekly", "monthly", "once"]
QuotaAction = Literal["add", "remove", "set"]


@dataclass(slots=True)
class UserQuotaRecord:
    """用户额度记录。"""

    period_key: str
    used: int = 0
    quota_override: int | None = None
    reservation_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class QuotaReservation:
    """绑定实际消费周期的额度凭据；同一凭据最多退回一次。"""

    quota_key: str
    period: QuotaPeriod
    period_key: str
    default_quota: int
    reservation_id: str


class UserQuotaStore:
    """管理用户绘图次数。"""

    def __init__(self, path: Path, logger: Any | None = None) -> None:
        self._lock = RLock()
        self.path = path
        self.logger = logger
        self.records: dict[str, UserQuotaRecord] = {}
        self._load_failed = False

    def bind_logger(self, logger: Any | None) -> None:
        """绑定运行期 logger。"""

        self.logger = logger

    @synchronized
    def load(self) -> None:
        """读取额度数据。"""

        self._load_failed = True
        if not self.path.exists():
            self.records = {}
            self._load_failed = False
            return
        try:
            raw_data = read_json_file(self.path)
        except (OSError, ValueError) as exc:
            raise ValueError("用户额度文件无法读取，已保留原件，请从备份恢复") from exc
        if not isinstance(raw_data, dict):
            raise ValueError("用户额度文件格式不正确，已保留原件")

        records: dict[str, UserQuotaRecord] = {}
        fields = {"period_key", "used", "quota_override", "reservation_ids"}
        for user_id, payload in raw_data.items():
            if (
                not isinstance(user_id, str) or not user_id.strip()
                or not isinstance(payload, dict) or payload.keys() - fields
                or not {"period_key", "used"} <= payload.keys()
                or not isinstance(payload["period_key"], str) or not payload["period_key"].strip()
                or type(payload["used"]) is not int or payload["used"] < 0
                or (payload.get("quota_override") is not None and (
                    type(payload["quota_override"]) is not int or payload["quota_override"] < 0
                ))
            ):
                raise ValueError("用户额度记录格式不正确或包含未知字段，已保留原件")
            reservation_ids = payload.get("reservation_ids", [])
            if (
                not isinstance(reservation_ids, list)
                or any(not isinstance(value, str) or not value for value in reservation_ids)
                or len(reservation_ids) != len(set(reservation_ids))
            ):
                raise ValueError("用户额度预留记录格式不正确，已保留原件")
            records[user_id] = UserQuotaRecord(
                period_key=payload["period_key"],
                used=payload["used"],
                quota_override=payload.get("quota_override"),
                reservation_ids=list(reservation_ids),
            )
        self.records = records
        self._load_failed = False

    @synchronized
    def save(self) -> None:
        """保存额度数据。"""

        if self._load_failed:
            raise ValueError("用户额度文件尚未恢复，拒绝覆盖原件")
        write_json_atomically(
            self.path,
            {user_id: asdict(record) for user_id, record in self.records.items()},
        )

    @synchronized
    def get_remaining(self, user_id: str, *, period: QuotaPeriod, default_quota: int) -> int:
        """获取当前周期剩余次数。"""

        record = self._get_record(user_id, period)
        quota = self._resolve_quota(record, default_quota)
        return max(quota - record.used, 0)

    @synchronized
    def consume(self, user_id: str, *, period: QuotaPeriod, default_quota: int) -> tuple[bool, int]:
        """消耗一次额度，返回是否成功与剩余次数。"""

        record = self._get_record(user_id, period)
        quota = self._resolve_quota(record, default_quota)
        if record.used >= quota:
            return False, 0
        record.used += 1
        self._commit_record(user_id, record)
        return True, max(quota - record.used, 0)

    @synchronized
    def reserve(
        self, user_id: str, *, period: QuotaPeriod, default_quota: int
    ) -> tuple[QuotaReservation | None, int]:
        """原子保存消费与凭据，返回凭据和剩余额度。"""

        record = self._get_record(user_id, period)
        quota = self._resolve_quota(record, default_quota)
        if record.used >= quota:
            return None, 0
        reservation = QuotaReservation(
            quota_key=user_id,
            period=period,
            period_key=record.period_key,
            default_quota=default_quota,
            reservation_id=uuid4().hex,
        )
        record.used += 1
        record.reservation_ids.append(reservation.reservation_id)
        self._commit_record(user_id, record)
        return reservation, max(quota - record.used, 0)

    @synchronized
    def refund_reservation(self, reservation: QuotaReservation) -> int:
        """只释放凭据对应的消费；已退款或已淘汰周期均不改变额度。"""

        return self._settle_reservation(reservation, refund=True)

    @synchronized
    def commit_reservation(self, reservation: QuotaReservation) -> int:
        """成功任务保留消费并移除凭据，后续重复结算不再生效。"""

        return self._settle_reservation(reservation, refund=False)

    def _settle_reservation(self, reservation: QuotaReservation, *, refund: bool) -> int:
        record = self.records.get(reservation.quota_key)
        if (
            record is None
            or record.period_key != reservation.period_key
            or reservation.reservation_id not in record.reservation_ids
        ):
            return self.get_remaining(
                reservation.quota_key,
                period=reservation.period,
                default_quota=reservation.default_quota,
            )
        record = replace(record, reservation_ids=list(record.reservation_ids))
        if refund:
            record.used = max(record.used - 1, 0)
        record.reservation_ids.remove(reservation.reservation_id)
        quota = self._resolve_quota(record, reservation.default_quota)
        self._commit_record(reservation.quota_key, record)
        return max(quota - record.used, 0)

    @synchronized
    def refund(self, user_id: str, *, period: QuotaPeriod, default_quota: int) -> int:
        """回退一次已消耗额度，并返回回退后的剩余次数。"""

        record = self._get_record(user_id, period)
        # 旧接口只退回无凭据消费，不能释放其他任务仍持有的预留。
        record.used = max(record.used - 1, len(record.reservation_ids))
        quota = self._resolve_quota(record, default_quota)
        self._commit_record(user_id, record)
        return max(quota - record.used, 0)

    @synchronized
    def adjust_remaining(
        self,
        user_id: str,
        *,
        action: QuotaAction,
        count: int,
        period: QuotaPeriod,
        default_quota: int,
    ) -> int:
        """调整用户当前周期剩余次数，并返回调整后的剩余次数。"""

        record = self._get_record(user_id, period)
        quota = self._resolve_quota(record, default_quota)
        remaining = max(quota - record.used, 0)
        if action == "add":
            next_remaining = remaining + count
        elif action == "remove":
            next_remaining = max(remaining - count, 0)
        else:
            next_remaining = max(count, 0)
        record.quota_override = record.used + next_remaining
        self._commit_record(user_id, record)
        return next_remaining

    def _commit_record(self, user_id: str, record: UserQuotaRecord) -> None:
        """在锁内提交写时复制状态，保存失败保留原记录及原凭据。"""

        previous_records = self.records
        self.records = {**previous_records, user_id: record}
        try:
            self.save()
        except BaseException:
            self.records = previous_records
            raise

    @classmethod
    def _period_key(cls, period: QuotaPeriod) -> str:
        now = datetime.now()
        if period == "daily":
            return now.strftime("%Y-%m-%d")
        if period == "weekly":
            year, week, _ = now.isocalendar()
            return f"{year}-W{week:02d}"
        if period == "monthly":
            return now.strftime("%Y-%m")
        return "once"

    def _get_record(self, user_id: str, period: QuotaPeriod) -> UserQuotaRecord:
        period_key = self._period_key(period)
        record = self.records.get(user_id)
        if record is None or record.period_key != period_key:
            return UserQuotaRecord(period_key=period_key)
        return replace(record, reservation_ids=list(record.reservation_ids))

    @staticmethod
    def _resolve_quota(record: UserQuotaRecord, default_quota: int) -> int:
        if record.quota_override is not None:
            return max(record.quota_override, 0)
        return max(int(default_quota), 0)

    def _log_warning(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.warning(message, *args)
