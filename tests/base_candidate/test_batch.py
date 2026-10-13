"""Binary Git framing and bounded process guards; synthetic content only."""

import hashlib
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from project_workflow.infrastructure import base_package as package


def blob(body=b"Synthetic instruction\r\n", path="roles/developer.md"):
    oid = hashlib.sha1(f"blob {len(body)}\0".encode("ascii") + body).hexdigest()
    return package._Blob(path, oid, len(body))


def packet(entry, body):
    return f"{entry.oid} blob {entry.size}\n".encode("ascii") + body + b"\n"


def tree(entry, mode="100644", kind="blob"):
    return f"{mode} {kind} {entry.oid} {entry.size}\tagent-skills/{entry.path}\0".encode("ascii")


def test_batch_roundtrip_keeps_exact_bytes_and_normalized_digest():
    body = b"Synthetic instruction\r\n"
    entry = blob(body)
    files = package._decode_batch([entry], packet(entry, body))
    assert files == {entry.path: body}
    assert package.digest(files[entry.path]) == hashlib.sha256(body.replace(b"\r\n", b"\n")).hexdigest()


@pytest.mark.parametrize("change", [
    "oid", "kind", "size", "missing", "header-newline", "short-body", "long-body",
    "trailer", "trailing", "extra-packet", "body-hash", "utf8",
])
def test_malformed_batch_fails_closed(change):
    body = b"Synthetic instruction\n"
    entry = blob(body)
    raw = packet(entry, body)
    if change == "oid":
        raw = b"0" * 40 + raw[40:]
    elif change == "kind":
        raw = raw.replace(b" blob ", b" tree ")
    elif change == "size":
        raw = raw.replace(f"blob {entry.size}".encode(), b"blob 999999999")
    elif change == "missing":
        raw = f"{entry.oid} missing\n".encode()
    elif change == "header-newline":
        raw = raw.replace(b"\n", b"\r\n", 1)
    elif change == "short-body":
        raw = raw[:-2]
    elif change == "long-body":
        raw = packet(entry, body + b"unexpected")
    elif change == "trailer":
        raw = raw[:-1] + b"!"
    elif change == "trailing":
        raw += b"\n"
    elif change == "extra-packet":
        raw += raw
    elif change == "body-hash":
        raw = packet(entry, b"X" * entry.size)
    elif change == "utf8":
        body = b"\xff" * entry.size
        entry = blob(body)
        raw = packet(entry, body)
    with pytest.raises(ValueError):
        package._decode_batch([entry], raw)


def test_out_of_order_or_duplicate_batch_is_not_accepted():
    first, second = blob(b"First\n"), blob(b"Second\n", "roles/analyst.md")
    with pytest.raises(ValueError):
        package._decode_batch([first, second], packet(second, b"Second\n") + packet(first, b"First\n"))
    with pytest.raises(ValueError):
        package._decode_batch([first, first], packet(first, b"First\n") * 2)


@pytest.mark.parametrize("size", [0, -1, package.MAX_BLOB_BYTES + 1, 10**20])
def test_invalid_size_rejected_before_batch_process(size, monkeypatch):
    raw = tree(blob()).replace(f"blob {blob().oid} {blob().size}".encode(), f"blob {blob().oid} {size}".encode())
    command = Mock(return_value=raw)
    monkeypatch.setattr(package, "git", command)
    with pytest.raises(ValueError):
        package.GitPackage(Path("synthetic"), "a" * 40).files()
    assert command.call_count == 1
    assert command.call_args.args[1] == "ls-tree"


@pytest.mark.parametrize("mode,kind", [("120000", "blob"), ("160000", "commit"), ("040000", "tree")])
def test_nonregular_inventory_rejected_before_batch(mode, kind, monkeypatch):
    command = Mock(return_value=tree(blob(), mode, kind))
    monkeypatch.setattr(package, "git", command)
    with pytest.raises(ValueError):
        package.GitPackage(Path("synthetic"), "a" * 40).files()
    assert command.call_count == 1


@pytest.mark.parametrize("raw", [
    b"", b"invalid\0", b"\xff\0", tree(blob())[:-1], tree(blob()) * 2,
    tree(blob()).replace(b"agent-skills/roles/developer.md", b"agent-skills/roles/../../outside"),
    tree(blob()).replace(b"agent-skills/roles/developer.md", b"agent-skills/roles/developer.md\nHEAD"),
    tree(blob()).replace(b"agent-skills/", b"outside/"),
    b"x" * (package.MAX_TREE_BYTES + 1), tree(blob()) * (package.MAX_PACKAGE_BLOBS + 1),
], ids=["empty", "header", "utf8", "unterminated", "duplicate", "traversal", "newline", "outside", "size", "count"])
def test_malformed_inventory_is_not_a_valid_package(raw):
    with pytest.raises(ValueError):
        package._decode_inventory(raw)


@pytest.mark.parametrize("relative", [
    "HEAD", "../manifest.json", "roles/unknown.md", "skills//SKILL.md", "manifest.json\n",
])
def test_invalid_path_never_reaches_git(relative, monkeypatch):
    command = Mock(side_effect=AssertionError("Invalid request reached Git"))
    monkeypatch.setattr(package, "git", command)
    with pytest.raises(ValueError):
        package.GitPackage(Path("synthetic"), "a" * 40).read(relative)
    command.assert_not_called()


@pytest.mark.parametrize("script,timeout", [
    ("import sys; sys.stdout.buffer.write(b'x'*100000); sys.stdout.flush(); import time; time.sleep(10)", False),
    ("import time; time.sleep(10)", True),
    ("import os,time; os.close(1); time.sleep(10)", True),
])
def test_process_size_and_timeout_limits_kill_and_reap(script, timeout, monkeypatch, tmp_path):
    real = subprocess.Popen
    children = []

    def launch(args, **kwargs):
        assert "--no-replace-objects" in args
        assert "core.fsmonitor=false" in args
        assert kwargs["env"]["GIT_NO_LAZY_FETCH"] == "1"
        assert kwargs["env"]["GIT_ALLOW_PROTOCOL"] == ""
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        child = real([sys.executable, "-c", script], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setattr(package, "GIT_TIMEOUT_SECONDS", 1 if timeout else 5)
    started = time.perf_counter()
    with pytest.raises(ValueError, match="bound|unavailable"):
        package.git(tmp_path, "cat-file", "--batch", input=b"a" * 40 + b"\n", max_output_bytes=128)
    assert time.perf_counter() - started < 5
    assert len(children) == 1 and children[0].poll() is not None


def test_oversized_batch_input_never_spawns_git(monkeypatch, tmp_path):
    command = Mock(side_effect=AssertionError("Oversized input spawned Git"))
    monkeypatch.setattr(subprocess, "Popen", command)
    with pytest.raises(ValueError, match="input exceeds"):
        package.git(tmp_path, "cat-file", "--batch", input=b"x" * (package.MAX_PACKAGE_BLOBS * 41 + 1))
    command.assert_not_called()


def test_batch_reads_all_21_files_in_one_process(monkeypatch):
    paths = ["manifest.json", *sorted(package._ROLE_FILES), *(f"skills/synthetic-{i}/SKILL.md" for i in range(14))]
    entries = [blob(f"Synthetic file {index}\n".encode(), path) for index, path in enumerate(paths)]
    inventory = b"".join(tree(entry) for entry in entries)
    raw = b"".join(packet(entry, f"Synthetic file {index}\n".encode()) for index, entry in enumerate(entries))
    command = Mock(side_effect=[inventory, raw])
    monkeypatch.setattr(package, "git", command)
    files = package.GitPackage(Path("synthetic"), "a" * 40).files()
    assert set(files) == set(paths)
    assert command.call_count == 2
    args, kwargs = command.call_args
    assert args[1:] == ("cat-file", "--batch")
    assert kwargs["input"] == b"".join(f"{entry.oid}\n".encode() for entry in entries)
    assert kwargs["max_output_bytes"] == len(raw)
