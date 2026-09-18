from concurrent.futures import ThreadPoolExecutor

import pytest

from quant.data.cache import (
    MemoryCache,
    RedisCache,
    SqliteCache,
    supports_execution_transactions,
    supports_trusted_atomic_update,
)


APPROVAL_KEY = "adaptive:model_health:approval:review-42"
CONSUMPTION_KEY = "adaptive:model_health:approval_consumed:review-42"


class ExplodingCopy:
    def __deepcopy__(self, memo):
        raise TypeError("cannot copy")


class FakeRedisClient:
    def __init__(self):
        self.values = {}
        self.set_calls = []
        self.flushdb_calls = 0

    def set(self, key, value, **kwargs):
        self.set_calls.append((key, value, kwargs))
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    def setex(self, key, _ttl, value):
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)

    def scan_iter(self, match=None, count=None):
        yield from list(self.values)

    def keys(self, pattern="*"):
        return list(self.values)

    def dbsize(self):
        return len(self.values)

    def flushdb(self):
        self.flushdb_calls += 1
        self.values.clear()

    def pipeline(self):
        return FakeRedisPipeline(self)


class FakeRedisPipeline:
    def __init__(self, client):
        self.client = client
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.commands = []

    def watch(self, *keys):
        return None

    def mget(self, keys):
        return [self.client.get(key) for key in keys]

    def multi(self):
        return None

    def set(self, key, value):
        self.commands.append(("set", key, value, None))

    def setex(self, key, ttl, value):
        self.commands.append(("setex", key, value, ttl))

    def execute(self):
        pending = dict(self.client.values)
        for _command, key, value, _ttl in self.commands:
            pending[key] = value
        self.client.values = pending
        return [True] * len(self.commands)


def make_redis_cache():
    cache = RedisCache.__new__(RedisCache)
    cache._client = FakeRedisClient()
    cache._default_ttl = 60
    return cache


def test_official_cache_types_declare_trusted_atomic_update(tmp_path):
    sqlite_cache = SqliteCache(str(tmp_path / "trusted-atomic.db"), default_ttl=None)
    try:
        assert supports_trusted_atomic_update(sqlite_cache) is True
        assert supports_trusted_atomic_update(MemoryCache(default_ttl=None)) is True
        assert supports_trusted_atomic_update(make_redis_cache()) is True
    finally:
        sqlite_cache._conn.close()


def test_only_file_backed_exact_sqlite_has_execution_semantics(tmp_path):
    sqlite_cache = SqliteCache(str(tmp_path / "execution-compatible.db"))

    class SqliteSubclass(SqliteCache):
        pass

    subclass_cache = SqliteSubclass(str(tmp_path / "subclass.db"))
    try:
        assert supports_execution_transactions(sqlite_cache) is True
        assert supports_execution_transactions(MemoryCache(default_ttl=None)) is False
        assert supports_execution_transactions(make_redis_cache()) is False
        assert supports_execution_transactions(subclass_cache) is False
    finally:
        sqlite_cache._conn.close()
        subclass_cache._conn.close()


def test_trusted_atomic_rejects_forged_capability():
    class ForgedCache:
        atomic_update_capability = "quant.cache.atomic_update.v1"

        def atomic_update(self, keys, updater):
            return updater({key: None for key in keys})

    assert supports_trusted_atomic_update(ForgedCache()) is False


def test_trusted_atomic_rejects_backend_subclass():
    class ForgedMemoryCache(MemoryCache):
        pass

    assert supports_trusted_atomic_update(ForgedMemoryCache(default_ttl=None)) is False


def test_trusted_atomic_rejects_instance_method_override():
    cache = MemoryCache(default_ttl=None)
    cache.atomic_update = lambda keys, updater: updater({key: None for key in keys})

    assert supports_trusted_atomic_update(cache) is False


def test_trusted_atomic_rejects_class_method_override(monkeypatch):
    monkeypatch.setattr(
        MemoryCache,
        "atomic_update",
        lambda self, keys, updater: updater({key: None for key in keys}),
    )

    assert supports_trusted_atomic_update(MemoryCache(default_ttl=None)) is False


def test_redis_atomic_update_writes_all_keys_together():
    cache = make_redis_cache()
    cache.set("left", 1)
    cache.set("right", 2)

    result = cache.atomic_update(
        ["left", "right"],
        lambda snapshot: {
            "left": snapshot["left"] + 10,
            "right": snapshot["right"] + 20,
        },
    )

    assert result == {"left": 11, "right": 22}
    assert cache.get("left") == 11
    assert cache.get("right") == 22


def test_redis_atomic_update_updater_exception_leaves_all_keys_unchanged():
    cache = make_redis_cache()
    cache.set("left", 1)
    cache.set("right", 2)

    def fail(_snapshot):
        raise RuntimeError("updater failed")

    with pytest.raises(RuntimeError, match="updater failed"):
        cache.atomic_update(["left", "right"], fail)

    assert cache.get("left") == 1
    assert cache.get("right") == 2


@pytest.fixture(params=["memory", "sqlite"])
def cache(request, tmp_path):
    if request.param == "memory":
        instance = MemoryCache(default_ttl=None)
    else:
        instance = SqliteCache(str(tmp_path / "atomic.db"), default_ttl=None)
    try:
        yield instance
    finally:
        if isinstance(instance, SqliteCache):
            instance._conn.close()


def test_atomic_update_writes_multiple_keys_from_one_snapshot(cache):
    cache.set("left", {"count": 1})
    cache.set("right", [])

    written = cache.atomic_update(
        ["left", "right"],
        lambda snapshot: {
            "left": {"count": snapshot["left"]["count"] + 1},
            "right": [*snapshot["right"], "done"],
        },
    )

    assert written == {"left": {"count": 2}, "right": ["done"]}
    written["left"]["count"] = 999
    assert cache.get("left") == {"count": 2}
    assert cache.get("right") == ["done"]


def test_atomic_update_updater_error_leaves_all_keys_unchanged(cache):
    cache.set("left", 1)
    cache.set("right", 2)

    def fail(_snapshot):
        raise RuntimeError("updater failed")

    with pytest.raises(RuntimeError, match="updater failed"):
        cache.atomic_update(["left", "right"], fail)

    assert cache.get("left") == 1
    assert cache.get("right") == 2


def test_atomic_update_preparation_error_leaves_all_keys_unchanged(cache):
    cache.set("left", 1)
    cache.set("right", 2)
    bad_value = ExplodingCopy()

    with pytest.raises((TypeError, ValueError)):
        cache.atomic_update(
            ["left", "right"],
            lambda _snapshot: {"left": 10, "right": bad_value},
        )

    assert cache.get("left") == 1
    assert cache.get("right") == 2


def test_sqlite_atomic_update_serialization_error_rolls_back_all_keys(tmp_path):
    cache = SqliteCache(str(tmp_path / "serialization.db"), default_ttl=None)
    try:
        cache.set("left", 1)
        cache.set("right", 2)
        circular = []
        circular.append(circular)

        with pytest.raises(ValueError, match="Circular reference"):
            cache.atomic_update(
                ["left", "right"],
                lambda _snapshot: {"left": 10, "right": circular},
            )

        assert cache.get("left") == 1
        assert cache.get("right") == 2
    finally:
        cache._conn.close()


def test_sqlite_atomic_update_backend_error_rolls_back_all_keys(tmp_path):
    cache = SqliteCache(str(tmp_path / "backend.db"), default_ttl=None)
    try:
        cache.set("left", 1)
        cache.set("right", 2)
        cache._conn.execute(
            """
            CREATE TRIGGER fail_right_update
            BEFORE INSERT ON kv
            WHEN NEW.key = 'right'
            BEGIN
                SELECT RAISE(ABORT, 'injected backend failure');
            END
            """
        )
        cache._conn.commit()

        with pytest.raises(Exception, match="injected backend failure"):
            cache.atomic_update(
                ["left", "right"],
                lambda _snapshot: {"left": 10, "right": 20},
            )

        assert cache.get("left") == 1
        assert cache.get("right") == 2
    finally:
        cache._conn.close()


def test_atomic_update_disallows_unrequested_keys(cache):
    cache.set("allowed", 1)

    with pytest.raises(ValueError, match="requested"):
        cache.atomic_update(
            ["allowed"],
            lambda _snapshot: {"allowed": 2, "other": 3},
        )

    assert cache.get("allowed") == 1
    assert cache.get("other") is None


def test_atomic_update_exposes_expired_requested_values_as_missing(cache):
    cache.set("expired", {"stale": True}, ttl=-1)

    written = cache.atomic_update(
        ["expired", "result"],
        lambda snapshot: {"result": {"expired_was": snapshot["expired"]}},
    )

    assert written == {"result": {"expired_was": None}}
    assert cache.get("expired") is None


def test_create_immutable_is_create_once_and_returns_defensive_copy(cache):
    source = {"approval_ref": "review-42", "nested": {"valid": True}}

    created = cache.create_immutable(APPROVAL_KEY, source)
    source["nested"]["valid"] = False
    created["nested"]["valid"] = False

    assert cache.get(APPROVAL_KEY)["nested"]["valid"] is True
    with pytest.raises((ValueError, KeyError), match="exist|immutable"):
        cache.create_immutable(APPROVAL_KEY, {"replacement": True})


def test_create_immutable_rejects_nonapproval_and_consumption_keys(cache):
    for key in ["ordinary", CONSUMPTION_KEY]:
        with pytest.raises(ValueError, match="approval"):
            cache.create_immutable(key, {})


def test_normal_apis_cannot_overwrite_delete_or_restore_approval(cache):
    original = {"approval_ref": "review-42", "authority": "immutable"}
    cache.create_immutable(APPROVAL_KEY, original)

    with pytest.raises(ValueError, match="protected"):
        cache.set(APPROVAL_KEY, {"authority": "replaced"})
    with pytest.raises(ValueError, match="protected"):
        cache.delete(APPROVAL_KEY)
    with pytest.raises(ValueError, match="protected"):
        cache.atomic_update(
            [APPROVAL_KEY], lambda _snapshot: {APPROVAL_KEY: original}
        )

    assert cache.get(APPROVAL_KEY) == original


def test_consumption_key_is_append_only_and_protected(cache):
    first = {"approval_ref": "review-42", "consumed_at": "first"}

    cache.atomic_update(
        [CONSUMPTION_KEY], lambda snapshot: {CONSUMPTION_KEY: first}
    )

    with pytest.raises(ValueError, match="append-only"):
        cache.atomic_update(
            [CONSUMPTION_KEY],
            lambda _snapshot: {CONSUMPTION_KEY: {"consumed_at": "second"}},
        )
    with pytest.raises(ValueError, match="protected"):
        cache.set(CONSUMPTION_KEY, {"consumed_at": "restored"})
    with pytest.raises(ValueError, match="protected"):
        cache.delete(CONSUMPTION_KEY)
    assert cache.get(CONSUMPTION_KEY) == first


def test_clear_preserves_protected_evidence_and_removes_ordinary_keys(cache):
    approval = {"approval_ref": "review-42", "authority": "immutable"}
    consumption = {"approval_ref": "review-42", "consumed_at": "first"}
    cache.create_immutable(APPROVAL_KEY, approval)
    cache.atomic_update(
        [CONSUMPTION_KEY],
        lambda _snapshot: {CONSUMPTION_KEY: consumption},
    )
    cache.set("ordinary", {"remove": True})

    cache.clear()

    assert cache.get("ordinary") is None
    assert cache.get(APPROVAL_KEY) == approval
    assert cache.get(CONSUMPTION_KEY) == consumption


def test_memory_get_returns_defensive_copies_for_protected_evidence():
    cache = MemoryCache(default_ttl=None)
    cache.create_immutable(
        APPROVAL_KEY,
        {"approval_ref": "review-42", "nested": {"valid": True}},
    )
    cache.atomic_update(
        [CONSUMPTION_KEY],
        lambda _snapshot: {
            CONSUMPTION_KEY: {
                "approval_ref": "review-42",
                "nested": {"consumed": True},
            }
        },
    )

    approval = cache.get(APPROVAL_KEY)
    consumption = cache.get(CONSUMPTION_KEY)
    approval["nested"]["valid"] = False
    consumption["nested"]["consumed"] = False

    assert cache.get(APPROVAL_KEY)["nested"]["valid"] is True
    assert cache.get(CONSUMPTION_KEY)["nested"]["consumed"] is True


def test_memory_set_stores_a_defensive_copy():
    cache = MemoryCache(default_ttl=None)
    source = {"nested": [1]}

    cache.set("ordinary", source)
    source["nested"].append(2)

    assert cache.get("ordinary") == {"nested": [1]}


def test_client_alias_cannot_mutate_or_clear_protected_evidence(cache):
    approval = {"approval_ref": "review-42"}
    consumption = {"approval_ref": "review-42", "consumed_at": "first"}
    cache.create_immutable(APPROVAL_KEY, approval)
    cache.atomic_update(
        [CONSUMPTION_KEY],
        lambda _snapshot: {CONSUMPTION_KEY: consumption},
    )
    cache.set("ordinary", 1)

    alias = cache.client
    with pytest.raises(ValueError, match="protected"):
        alias.set(APPROVAL_KEY, {"replacement": True})
    with pytest.raises(ValueError, match="protected"):
        alias.delete(CONSUMPTION_KEY)
    with pytest.raises(ValueError, match="immutable"):
        alias.atomic_update(
            [APPROVAL_KEY],
            lambda _snapshot: {APPROVAL_KEY: {"replacement": True}},
        )
    alias.clear()

    assert alias.get("ordinary") is None
    assert alias.get(APPROVAL_KEY) == approval
    assert alias.get(CONSUMPTION_KEY) == consumption


def test_concurrent_consumption_create_has_exactly_one_winner(cache):
    def consume(worker_id):
        try:
            cache.atomic_update(
                [CONSUMPTION_KEY],
                lambda _snapshot: {
                    CONSUMPTION_KEY: {"consumer": worker_id}
                },
            )
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(consume, ["one", "two"]))

    assert sorted(outcomes) == [False, True]
    assert cache.get(CONSUMPTION_KEY)["consumer"] in {"one", "two"}


@pytest.mark.parametrize("keys", [[], [""], ["a", "a"], ["a", 1]])
def test_atomic_update_validates_requested_keys(cache, keys):
    with pytest.raises(ValueError, match="keys"):
        cache.atomic_update(keys, lambda _snapshot: {})


def test_concurrent_atomic_updates_do_not_lose_counts_or_mapping_entries(cache):
    cache.set("counter", 0)
    cache.set("merged", {})

    def update(worker_id):
        for iteration in range(40):
            token = f"{worker_id}-{iteration}"

            def updater(snapshot):
                return {
                    "counter": snapshot["counter"] + 1,
                    "merged": {**snapshot["merged"], token: True},
                }

            cache.atomic_update(["counter", "merged"], updater)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(update, range(4)))

    assert cache.get("counter") == 160
    assert len(cache.get("merged")) == 160


def test_redis_create_immutable_uses_persistent_set_nx_and_protects_normal_apis():
    cache = make_redis_cache()

    created = cache.create_immutable(APPROVAL_KEY, {"approval_ref": "review-42"})

    assert created == {"approval_ref": "review-42"}
    assert cache._client.set_calls[0][2] == {"nx": True}
    with pytest.raises((ValueError, KeyError)):
        cache.create_immutable(APPROVAL_KEY, {"replacement": True})
    with pytest.raises(ValueError, match="protected"):
        cache.set(APPROVAL_KEY, {})
    with pytest.raises(ValueError, match="protected"):
        cache.delete(CONSUMPTION_KEY)


def test_redis_clear_preserves_protected_evidence_and_removes_ordinary_keys():
    cache = make_redis_cache()
    approval = {"approval_ref": "review-42"}
    consumption = {"approval_ref": "review-42", "consumed_at": "first"}
    cache.create_immutable(APPROVAL_KEY, approval)
    cache._client.set(CONSUMPTION_KEY, '{"approval_ref": "review-42", "consumed_at": "first"}')
    cache.set("ordinary", {"remove": True})

    cache.clear()

    assert cache.get("ordinary") is None
    assert cache.get(APPROVAL_KEY) == approval
    assert cache.get(CONSUMPTION_KEY) == consumption
    assert cache._client.flushdb_calls == 0


def test_redis_client_alias_is_restricted_cache_facade():
    cache = make_redis_cache()
    approval = {"approval_ref": "review-42"}
    cache.create_immutable(APPROVAL_KEY, approval)
    cache.set("ordinary", 1)

    alias = cache.client

    assert alias is cache
    assert not hasattr(alias, "flushdb")
    with pytest.raises(ValueError, match="protected"):
        alias.set(APPROVAL_KEY, {"replacement": True})
    with pytest.raises(ValueError, match="protected"):
        alias.delete(APPROVAL_KEY)
    alias.clear()
    assert alias.get("ordinary") is None
    assert alias.get(APPROVAL_KEY) == approval
