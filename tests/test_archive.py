import json

from alpha.data import archive


def test_store_writes_file_and_manifest(tmp_path):
    p = archive.store("src", "a/b.csv", b"hello", "http://x/b.csv", root=tmp_path)
    assert p == tmp_path / "src" / "a" / "b.csv"
    assert p.read_bytes() == b"hello"
    m = json.loads(archive.manifest_path(p).read_text())
    assert m["url"] == "http://x/b.csv"
    assert m["size"] == 5
    assert m["supersedes"] is None


def test_identical_refetch_is_noop(tmp_path):
    p1 = archive.store("src", "a.csv", b"same", "http://x", root=tmp_path)
    mtime = archive.manifest_path(p1).stat().st_mtime_ns
    p2 = archive.store("src", "a.csv", b"same", "http://x", root=tmp_path)
    assert p1 == p2
    assert archive.manifest_path(p1).stat().st_mtime_ns == mtime


def test_conflicting_refetch_never_overwrites(tmp_path):
    p1 = archive.store("src", "a.csv", b"v1", "http://x", root=tmp_path)
    p2 = archive.store("src", "a.csv", b"v2", "http://x", root=tmp_path)
    assert p1 != p2
    assert p1.read_bytes() == b"v1"  # original untouched
    assert p2.name == "a.csv.rev1"
    assert json.loads(archive.manifest_path(p2).read_text())["supersedes"] == "a.csv"


def test_is_archived(tmp_path):
    assert not archive.is_archived("src", "a.csv", root=tmp_path)
    archive.store("src", "a.csv", b"x", "http://x", root=tmp_path)
    assert archive.is_archived("src", "a.csv", root=tmp_path)
