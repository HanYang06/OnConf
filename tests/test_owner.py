# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""专职写者：选主、传输、以及「退到底」那一层。"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from onconf import (
    ConfError,
    Engine,
    KeyHasNoValueError,
    KeyNotRegisteredError,
    _owner,
)
from onconf._core import MISSING, Decl


def _open(home: Path) -> Engine:
    return Engine(home=str(home))


def _writer(home: Path) -> _owner.Owner:
    """起一个写者。执行入口是引擎的**就地执行**方法（以绑定方法传进去）。"""
    engine = _open(home)
    writer = _owner.Owner.claim(engine, engine._execute_local)
    assert writer is not None, "第一次抢绑应该抢得到"
    writer.start()
    return writer


def _client(home: Path) -> tuple[Engine, _owner.Channel]:
    """开一个**客户端**通道（写者已经被别人占着）。"""
    engine = _open(home)
    return engine, _owner.Channel(engine, engine._execute_local)


def _commit(*decls: Decl, clean: bool = False) -> _owner.Request:
    return _owner.Request(op=_owner.OP_COMMIT, decls=decls, clean=clean)


# --------------------------------------------------------------------------- #
# 选主的原料：端点名与认证码
# --------------------------------------------------------------------------- #


def test_endpoint_is_a_function_of_the_config_dir(tmp_path: Path) -> None:
    """端点名只看配置目录 —— 两个目录一个世界，用户不用配任何东西。"""
    here = tmp_path / "here"
    there = tmp_path / "there"

    assert _owner.endpoint_for(here) == _owner.endpoint_for(here)
    assert _owner.endpoint_for(here) != _owner.endpoint_for(there)

    if os.name == "nt":
        assert _owner.endpoint_for(here).startswith("\\\\.\\pipe\\onconf-")
        # 大小写不同的**同一个**目录必须映射到同一个端点：分成两个就是两个写者
        # 写同一个目录，而这正是本模块要防的事。
        assert _owner.endpoint_for(here) == _owner.endpoint_for(tmp_path / "Here")
    else:  # pragma: no cover - 本机是 Windows
        assert Path(_owner.endpoint_for(here)).parent == here / "schema"
        assert _owner.endpoint_for(here) != _owner.endpoint_for(tmp_path / "Here")


def test_authkey_is_created_once_and_atomically(tmp_path: Path) -> None:
    """认证码只能有一把：并发的首次创建者拿到不同的钥匙 = 有一个永远连不上。"""
    home = tmp_path / "conf"
    first = _owner.authkey_for(home)

    assert len(bytes.fromhex(first)) == _owner._KEY_BYTES
    assert _owner.authkey_for(home) == first
    assert (home / _owner.KEY_NAME).is_file()

    # 并发的首次创建（目录是全新的）
    fresh = tmp_path / "fresh"
    seen: list[str] = []
    start = threading.Barrier(2)

    def grab() -> None:
        start.wait()
        seen.append(_owner.authkey_for(fresh))

    workers = [threading.Thread(target=grab) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5)

    assert len(seen) == 2
    assert len(set(seen)) == 1, "并发首次创建生成了两把钥匙"


# --------------------------------------------------------------------------- #
# 选主：抢绑端点
# --------------------------------------------------------------------------- #


def test_binding_the_endpoint_is_the_election(tmp_path: Path) -> None:
    """**抢绑本身就是选举** —— 第二次绑定必须被操作系统拒掉。"""
    home = tmp_path / "conf"
    first = _owner.claim(home)
    assert first is not None, "第一个 Listener 应该绑得上"
    try:
        assert _owner.claim(home) is None, "第二个 Listener 不该绑得上"
    finally:
        first.close()
    # 让位之后，别人又抢得到了
    again = _owner.claim(home)
    assert again is not None
    again.close()


# --------------------------------------------------------------------------- #
# 两个踩过的坑，各钉一条回归
# --------------------------------------------------------------------------- #


def test_connect_is_bounded_when_nobody_answers(tmp_path: Path) -> None:
    """端点「有人听、没人答」时，``connect`` 必须**有界返回**，不是挂死。

    这条是踩出来的：``authkey=`` 让 ``Client(...)`` 在构造函数里做一次**没有
    超时**的挑战应答，于是 ``conf()`` 挂死在 ``recv_bytes`` 里。现在认证搬到
    应用层自己打招呼，等待因此有界。
    """
    home = tmp_path / "conf"
    listener = _owner.claim(home)  # 绑上，但**故意不开应答线程**
    assert listener is not None

    started = time.monotonic()
    try:
        assert _owner.connect(home, timeout=0.2) is None
    finally:
        listener.close()

    assert time.monotonic() - started < 5.0, "connect 没有在超时后返回"


def test_close_releases_the_endpoint(tmp_path: Path) -> None:
    """写者下班后端点必须**真的**还回来，否则下一个进程永远当不上写者。

    这条也是踩出来的：``Listener.close()`` 关的是队列里那个**备用**实例，
    而正在 ``accept()`` 里阻塞等待的那个 handle 由线程自己拿着、关不掉 ——
    端点名一直挂着，下一个进程抢绑永远失败（写者真空）。所以 ``close()``
    要先开一条空连接把线程叫醒，再等它收摊。
    """
    home = tmp_path / "conf"
    writer = _writer(home)
    writer.close()

    assert _owner.connect(home, timeout=0.2) is None
    second = _owner.claim(home)
    assert second is not None, "上一个写者下班后端点没释放"
    second.close()


# --------------------------------------------------------------------------- #
# 传输
# --------------------------------------------------------------------------- #


def test_the_sentinel_is_restored_by_name() -> None:
    """哨兵过线靠 ``__reduce__`` 还原成模块级单例，不是重建一个同名对象。"""
    assert MISSING.__reduce__() == "MISSING"


def test_a_doc_only_declaration_keeps_its_missing_value_across_the_wire(
    tmp_path: Path,
) -> None:
    """``conf(key, doc=…)`` 的 value 位是 ``MISSING``，它必须原样过线。

    判据很直接：只登记不给值之后立刻读，**必须报「登记了但没值」**。要是哨兵在
    过线时被 pickle 重建成一个新对象，词表里就会记下一个「默认值」—— 那正是那个
    哨兵本身 —— 于是这里会**静默返回一个对象**而不是报错。
    """
    home = tmp_path / "conf"
    writer = _writer(home)
    engine, channel = _client(home)
    try:
        channel.submit(_commit(Decl(key="api_key", doc="必填")))
        with pytest.raises(KeyHasNoValueError):
            engine("api_key")
    finally:
        channel.close()
        writer.close()


def test_client_declaration_lands_in_the_owners_file(tmp_path: Path) -> None:
    """客户端交的声明，最终由**写者**落进文件；客户端自己一根手指都没碰文件。"""
    home = tmp_path / "conf"
    writer = _writer(home)
    engine, channel = _client(home)
    try:
        assert channel.is_mine() is False, "写者已经被占了，它只能当客户端"

        channel.submit(_commit(Decl(key="port", value=8080)))

        written = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        assert written["port"] == 8080
        assert engine._loaded is False, "客户端不该自己读过写过一个字节"
        assert engine("port") == 8080, "读也要经过写者"
    finally:
        channel.close()
        writer.close()


def test_engine_errors_keep_their_type_across_the_wire(tmp_path: Path) -> None:
    """异常按名字过线：**类型不丢**，消息也不丢。"""
    home = tmp_path / "conf"
    writer = _writer(home)
    engine, channel = _client(home)
    try:
        with pytest.raises(KeyNotRegisteredError):
            engine("nope")
        with pytest.raises(ConfError, match="不认识的请求"):
            channel.submit(_owner.Request(op="nonsense"))
    finally:
        channel.close()
        writer.close()


def test_a_bad_authkey_is_turned_away(tmp_path: Path) -> None:
    """认证码对不上就不给服务 —— 连上了也只会被关掉。"""
    home = tmp_path / "conf"
    writer = _writer(home)
    try:
        conn = _owner._hello(_owner.endpoint_for(home), "00" * _owner._KEY_BYTES, 0.5)
        assert conn is None
    finally:
        writer.close()


# --------------------------------------------------------------------------- #
# 通道：写者 / 客户端 / 退到底
# --------------------------------------------------------------------------- #


def test_each_engine_builds_its_own_channel(tmp_path: Path) -> None:
    """**一个引擎一条通道** —— 不是「一个配置目录一条」。

    按目录共用的话，同一进程里第二个引擎会被塞进第一个引擎的通道，它的声明就
    落到另一个引擎的声明集上了。
    """
    engine = _open(tmp_path / "conf")
    first = engine._channel()
    assert engine._channel() is first

    engine.close()
    assert engine._chan is None


def test_channel_falls_back_to_direct_write_when_there_is_no_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """安全网：端点这条路整个不通时，**库还是能写**（OS 锁还在）。"""
    home = tmp_path / "conf"
    monkeypatch.setattr(_owner, "connect", lambda _home, **_kw: None)
    monkeypatch.setattr(_owner, "claim", lambda _home: None)

    engine = _open(home)
    channel = _owner.Channel(engine, engine._execute_local)
    assert channel.is_mine() is False

    channel.submit(_commit(Decl(key="port", value=9090)))
    written = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    assert written["port"] == 9090
    channel.close()


def test_channel_falls_back_when_the_endpoint_blows_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端点这条路**抛异常**（不只是连不上）时，也必须退回就地执行。"""
    home = tmp_path / "conf"

    def boom(_home: Path, **_kw: object) -> None:
        raise OSError("配置目录只读 / 文件系统不支持硬链接 之类")

    monkeypatch.setattr(_owner, "connect", boom)
    engine = _open(home)
    channel = _owner.Channel(engine, engine._execute_local)

    channel.submit(_commit(Decl(key="port", value=1)))
    assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["port"] == 1
    channel.close()


def test_channel_reelects_after_the_writer_leaves(tmp_path: Path) -> None:
    """写者下班 ⇒ 连接断 ⇒ **重新选主**，请求一次都不能丢。"""
    home = tmp_path / "conf"
    writer = _writer(home)
    _engine, channel = _client(home)
    try:
        channel.submit(_commit(Decl(key="a", value=1)))

        writer.close()  # 下班：端点关了，手上那条连接也关了

        channel.submit(_commit(Decl(key="b", value=2)))
        assert channel.is_mine() is True, "没人抢得过它，它应该接手当写者"

        written = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        assert written["a"] == 1, "写者换人不能弄丢前一个人的东西"
        assert written["b"] == 2
    finally:
        channel.close()
