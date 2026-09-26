"""pytest 配置。

``tests/`` 下的部分脚本（verify_all / test_proxy / test_play / test_native）
是**需要真实网络与平台接口**的联调脚本，导入即执行，不适合作为 CI 单元测试。
这里把它们排除出 pytest 收集，避免 CI 变成联网测试。

离线单测： ``pytest`` （默认只收集 test_stream_state.py）
联调回归： ``python tests/verify_all.py`` 等，手动运行。
"""

collect_ignore = [
    "verify_all.py",
    "test_proxy.py",
    "test_play.py",
    "test_native.py",
]
