"""
远程同步服务（轻量）

提供两项按需功能：
- 列出远程目录结构（不传输文件）
- 按需拉取单个远程文件到本地 `LOCAL_SYNC_DIR`

该实现通过系统 ssh/scp 命令与远端通信，使用环境变量 REMOTE_* 配置。
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List

from app.config import settings
from app.models.schemas import FileItem, DirectoryContent
from io import BytesIO
import time
from collections import OrderedDict


class MemoryCache:
    """简单的内存缓存，支持 LRU 淘汰和 TTL。键为相对路径字符串，值为字节数据。

    存储结构使用 OrderedDict 维护最近使用顺序（键被访问时移动到末尾）。
    """

    def __init__(self):
        self.store = OrderedDict()  # key -> (bytes, size, created_at, last_access)
        self.total_bytes = 0

    def _now(self) -> float:
        return time.time()

    def get(self, key: str):
        clean = str(key).lstrip('/\\')
        if clean not in self.store:
            raise KeyError(clean)
        data, size, created, last = self.store.pop(clean)
        # TTL check
        ttl = settings.memory_cache_ttl_seconds
        if ttl and (self._now() - created) > ttl:
            self.total_bytes -= size
            raise KeyError(clean)
        # update last access and move to end (most recently used)
        last = self._now()
        self.store[clean] = (data, size, created, last)
        return data

    def has(self, key: str) -> bool:
        clean = str(key).lstrip('/\\')
        if clean not in self.store:
            return False
        data, size, created, last = self.store.get(clean)
        ttl = settings.memory_cache_ttl_seconds
        if ttl and (self._now() - created) > ttl:
            # expire
            self._remove(clean)
            return False
        return True

    def set(self, key: str, data: bytes):
        clean = str(key).lstrip('/\\')
        size = len(data)
        # if exists, remove old
        if clean in self.store:
            _, old_size, _, _ = self.store.pop(clean)
            self.total_bytes -= old_size

        created = self._now()
        last = created
        self.store[clean] = (data, size, created, last)
        self.total_bytes += size
        # enforce limits
        self._enforce_limits()

    def _remove(self, key: str):
        if key in self.store:
            _, size, _, _ = self.store.pop(key)
            self.total_bytes -= size

    def _enforce_limits(self):
        max_bytes = settings.memory_cache_max_bytes
        max_items = settings.memory_cache_max_items
        # Evict by LRU (oldest at front) until under limits
        while (max_bytes and self.total_bytes > max_bytes) or (max_items and len(self.store) > max_items):
            old_key, (data, size, created, last) = self.store.popitem(last=False)
            self.total_bytes -= size

    def clear(self):
        self.store.clear()
        self.total_bytes = 0

    def stats(self):
        return {
            "items": len(self.store),
            "bytes": self.total_bytes,
            "max_items": settings.memory_cache_max_items,
            "max_bytes": settings.memory_cache_max_bytes,
            "ttl_seconds": settings.memory_cache_ttl_seconds,
            "policy": settings.memory_cache_eviction_policy,
        }


# 内存缓存实例
memory_cache = MemoryCache()


def _remote_base() -> str:
    return str(settings.remote_dicom_dir)


def _is_local_source() -> bool:
    host = (settings.remote_host or "").strip().lower()
    return host in {"", "127.0.0.1", "localhost", "::1"}


def _ssh_prefix() -> List[str]:
    host = (settings.remote_host or "").strip()
    user = (settings.remote_user or "").strip()
    if not host or not user:
        raise RuntimeError("REMOTE_HOST and REMOTE_USER must be set in .env")
    return ["ssh", "-p", str(settings.remote_port), f"{user}@{host}"]


def _local_list_directory(base_path: Path, rel_path: str) -> DirectoryContent:
    clean_rel = rel_path.strip("/\\")
    target = base_path if not clean_rel else (base_path / Path(clean_rel))
    target = target.resolve()

    if not target.exists():
        raise RuntimeError(f"Local source directory not found: {target}")
    if not target.is_dir():
        raise RuntimeError(f"Local source path is not a directory: {target}")

    items = []
    for entry in target.iterdir():
        is_dir = entry.is_dir()
        is_dicom = False if is_dir else entry.suffix.lower() == ".dcm"
        try:
            size = None if is_dir else entry.stat().st_size
        except Exception:
            size = None
        try:
            modified_time = datetime.fromtimestamp(entry.stat().st_mtime)
        except Exception:
            modified_time = None

        display_path = "/" + entry.name if not clean_rel else "/" + clean_rel + "/" + entry.name
        items.append(FileItem(
            name=entry.name,
            path=display_path.replace("\\", "/"),
            is_dir=is_dir,
            is_dicom=is_dicom,
            size=size,
            modified_time=modified_time,
        ))

    items.sort(key=lambda x: (not x.is_dir, x.name.lower()))
    return DirectoryContent(path="/" + clean_rel, items=items, total=len(items))


def list_remote(rel_path: str = "") -> DirectoryContent:
    """列出远程目录（只返回元数据，不传输文件）

    返回结构与本地 `DirectoryContent` 兼容。
    """
    clean_rel = rel_path.strip("/\\")

    if _is_local_source():
        return _local_list_directory(Path(_remote_base()), clean_rel)

    remote_dir = _remote_base().rstrip("/")
    target = remote_dir
    if clean_rel:
        target = f"{target}/{clean_rel}"

    # 使用 find 输出：name<TAB>type<char>\tsize\tmtime_epoch\n
    find_cmd = f"find {shlex.quote(target)} -maxdepth 1 -mindepth 1 -printf '%f\t%y\t%s\t%T@\n'"
    cmd = _ssh_prefix() + [find_cmd]

    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ssh list failed: {proc.stderr.decode(errors='ignore')}")

    text = proc.stdout.decode(errors="ignore")
    items = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        name, typ, size_s, mtime_s = parts[0], parts[1], parts[2], parts[3]
        is_dir = typ == "d"
        size = int(size_s) if size_s.isdigit() else None
        try:
            modified_time = datetime.fromtimestamp(float(mtime_s))
        except Exception:
            modified_time = None

        is_dicom = False
        if not is_dir:
            lower = name.lower()
            if lower.endswith(".dcm"):
                is_dicom = True

        display_path = "/"
        if clean_rel:
            display_path = "/" + clean_rel + "/" + name
        else:
            display_path = "/" + name

        items.append(FileItem(
            name=name,
            path=display_path.replace("\\", "/"),
            is_dir=is_dir,
            is_dicom=is_dicom,
            size=size,
            modified_time=modified_time
        ))

    items.sort(key=lambda x: (not x.is_dir, x.name.lower()))
    return DirectoryContent(path="/" + clean_rel, items=items, total=len(items))


def fetch_remote_file(rel_path: str) -> Path | None:
    """按需拉取单个远程文件。

    - `disk` 模式：写入本地 `LOCAL_SYNC_DIR` 并返回本地路径
    - `memory` 模式：只缓存到内存，返回 `None`

    rel_path: 以 `/` 开头或不以 `/` 的相对路径
    """
    clean_rel = str(rel_path).lstrip("/\\")
    local_base = Path(settings.local_sync_dir)
    target_local = local_base.joinpath(clean_rel)

    # 内存模式：不写磁盘，读取文件字节到 memory_store 并返回内存字节
    if settings.fetch_mode == "memory":
        if _is_local_source():
            source_path = Path(_remote_base()).joinpath(clean_rel)
            if not source_path.exists():
                raise RuntimeError(f"Source file not found: {source_path}")
            data = source_path.read_bytes()
            memory_cache.set(clean_rel, data)
            return None

        # 远端读取：通过 ssh cat 获取字节
        remote_base = _remote_base().rstrip("/")
        remote_path = remote_base + "/" + clean_rel
        ssh_cmd = _ssh_prefix() + [f"cat {shlex.quote(remote_path)}"]
        proc = subprocess.run(ssh_cmd, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ssh cat failed: {proc.stderr.decode(errors='ignore')}")
        data = proc.stdout
        memory_cache.set(clean_rel, data)
        return None

    # disk 模式：写入本地并返回路径
    target_local.parent.mkdir(parents=True, exist_ok=True)
    if _is_local_source():
        source_path = Path(_remote_base()).joinpath(clean_rel)
        if not source_path.exists():
            raise RuntimeError(f"Source file not found: {source_path}")
        shutil.copy2(source_path, target_local)
        return target_local.resolve()

    remote_base = _remote_base().rstrip("/")
    remote_src = f"{settings.remote_user}@{settings.remote_host}:{shlex.quote(remote_base + '/' + clean_rel)}"

    cmd = ["scp", "-P", str(settings.remote_port), remote_src, str(target_local)]

    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"scp failed: {proc.stderr.decode(errors='ignore')}")

    return target_local.resolve()


def get_memory_bytes(rel_path: str) -> bytes:
    """返回内存中已缓存的字节，如果不存在则抛出 KeyError"""
    return memory_cache.get(rel_path)


def has_memory(rel_path: str) -> bool:
    return memory_cache.has(rel_path)


def clear_memory_cache() -> None:
    memory_cache.clear()


def memory_cache_stats() -> dict:
    return memory_cache.stats()
