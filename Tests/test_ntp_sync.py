"""NTP sync_time 统一入口测试.

覆盖:
- 正常路径:有 server 时调 build_time_sync
- 空 server 路径:走自动选最快(复用 Core.TimeSync)
- 失败降级:网络全挂时返回 offset_s=0.0 的 TimeSync
"""
import unittest
from unittest.mock import patch, MagicMock

from Core.Zhipu.config import AppConfig, Account
from Core.Zhipu.orchestrator import sync_time
from Core.Zhipu.timesync import TimeSync


def _make_cfg(ntp_server: str = "", ntp_sync_times: int = 3) -> AppConfig:
    return AppConfig(
        accounts=[Account(name='t', phone='13800000000')],
        target_plan='Max',
        billing_cycle='yearly',
        pay_channel='alipay',
        ntp_server=ntp_server,
        ntp_sync_times=ntp_sync_times,
        ntp_max_drift_ms=500,
    )


class SyncTimeTest(unittest.TestCase):

    def test_explicit_server_path(self):
        """传了 server,直接调 build_time_sync 走单 server 路径。"""
        cfg = _make_cfg("ntp.aliyun.com")

        # mock build_time_sync 返回一个固定 offset
        fake_ts = TimeSync(offset_s=0.123)
        with patch("Core.Zhipu.orchestrator.build_time_sync", return_value=fake_ts) as mock_bts:
            result = sync_time(cfg)
        self.assertEqual(result.offset_s, 0.123)
        mock_bts.assert_called_once_with("ntp.aliyun.com", samples=3)

    def test_empty_server_path(self):
        """空 server 时,build_time_sync 内部走自动选最快(我们用空字符串透传)。"""
        cfg = _make_cfg(ntp_server="")
        fake_ts = TimeSync(offset_s=-0.05)
        with patch("Core.Zhipu.orchestrator.build_time_sync", return_value=fake_ts) as mock_bts:
            result = sync_time(cfg)
        self.assertEqual(result.offset_s, -0.05)
        # 第一参数为空字符串(让 build_time_sync 走自动探测分支)
        self.assertEqual(mock_bts.call_args.args[0], "")

    def test_failure_degrades_to_local_clock(self):
        """NTP 全部失败时,降级到 offset=0.0 的 TimeSync,不抛。"""
        cfg = _make_cfg("ntp.aliyun.com")

        def boom(*args, **kwargs):
            raise RuntimeError("NTP 全失败(测试 mock)")

        with patch("Core.Zhipu.orchestrator.build_time_sync", side_effect=boom):
            result = sync_time(cfg)
        # 降级到 offset=0.0
        self.assertEqual(result.offset_s, 0.0)
        # TimeSync 实例
        self.assertIsInstance(result, TimeSync)

    def test_large_drift_warns_but_returns(self):
        """漂移大时只 warn,仍然返回(用户自己看日志决定要不要中止)。"""
        cfg = _make_cfg(ntp_sync_times=3)
        # offset=1.0s,drift=1000ms,阈值 500ms → 触发 warn
        fake_ts = TimeSync(offset_s=1.0)
        with patch("Core.Zhipu.orchestrator.build_time_sync", return_value=fake_ts):
            result = sync_time(cfg)
        self.assertEqual(result.offset_s, 1.0)


if __name__ == "__main__":
    unittest.main()