"""Tests for auto-install config generators.

Generators are pure functions — no I/O — so these tests are fully
deterministic and run on any OS. Password hashing via POSIX
:mod:`crypt` is exercised separately and skipped on Windows.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

import pytest

from agentboot.autoinstall import (
    DiskLayout,
    InstallProfile,
    NetworkConfig,
    User,
    generate_cloud_init,
    generate_for_os,
    generate_kickstart,
    generate_preseed,
    generate_windows_unattend,
)


# A deliberately boring "good" hash so tests don't depend on the
# host having crypt(3) available.
FAKE_HASH = (
    "$6$rounds=5000$fakesalt1234567$"
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ012345678901"
    "abcdefghijk"
)


def _basic_profile(**overrides) -> InstallProfile:
    user = User(
        username="admin",
        password_hash=FAKE_HASH,
        ssh_authorized_keys=["ssh-ed25519 AAAA... admin@laptop"],
        sudo=True,
    )
    p = InstallProfile(
        user=user,
        disk=DiskLayout(target="/dev/sda", mode="wipe", use_lvm=False),
        network=NetworkConfig(hostname="testbox", dhcp=True),
        timezone="Europe/Madrid",
        packages=["htop", "tmux"],
        runcmd=["echo hello > /tmp/boot.log"],
    )
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


# ---------------------------------------------------------------------------
# Password resolution
# ---------------------------------------------------------------------------


def test_user_requires_password_or_hash():
    u = User(username="x")
    with pytest.raises(ValueError):
        u.resolve_password_hash()


def test_user_returns_explicit_hash_without_calling_crypt():
    u = User(username="x", password_hash=FAKE_HASH)
    assert u.resolve_password_hash() == FAKE_HASH


@pytest.mark.skipif(sys.platform == "win32", reason="crypt(3) not on Windows")
def test_user_hashes_plaintext_on_posix():
    u = User(username="x", password="hunter2")
    h = u.resolve_password_hash()
    assert h.startswith("$6$")
    # Idempotent salts differ but both should validate the same password.
    import crypt  # type: ignore[import]
    assert crypt.crypt("hunter2", h) == h


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only path")
def test_user_plaintext_raises_on_windows():
    u = User(username="x", password="hunter2")
    with pytest.raises(NotImplementedError):
        u.resolve_password_hash()


# ---------------------------------------------------------------------------
# cloud-init
# ---------------------------------------------------------------------------


def test_cloud_init_emits_user_data_and_meta_data():
    files = generate_cloud_init(_basic_profile())
    paths = {f.path for f in files}
    assert paths == {"nocloud/user-data", "nocloud/meta-data"}


def test_cloud_init_user_data_contains_core_fields():
    files = generate_cloud_init(_basic_profile())
    body = next(f.contents for f in files if f.path.endswith("user-data"))
    assert body.startswith("#cloud-config\n")
    assert "autoinstall:" in body
    assert "username: admin" in body
    assert FAKE_HASH in body
    assert "hostname: testbox" in body
    assert "htop" in body and "tmux" in body
    assert "Europe/Madrid" in body


def test_cloud_init_dhcp_vs_static():
    p = _basic_profile()
    p.network = NetworkConfig(
        hostname="h", dhcp=False,
        static_ip="10.0.0.50/24", gateway="10.0.0.1",
        dns=["1.1.1.1"],
    )
    body = generate_cloud_init(p)[0].contents
    assert "dhcp4: false" in body
    assert "10.0.0.50/24" in body
    assert "10.0.0.1" in body


def test_cloud_init_meta_data_has_hostname():
    files = generate_cloud_init(_basic_profile())
    md = next(f.contents for f in files if f.path.endswith("meta-data"))
    assert "local-hostname: testbox" in md


# ---------------------------------------------------------------------------
# Preseed
# ---------------------------------------------------------------------------


def test_preseed_single_file_with_expected_keys():
    files = generate_preseed(_basic_profile())
    assert len(files) == 1
    body = files[0].contents
    assert "d-i passwd/username string admin" in body
    assert f"d-i passwd/user-password-crypted password {FAKE_HASH}" in body
    assert "d-i netcfg/get_hostname string testbox" in body
    assert "d-i time/zone string Europe/Madrid" in body
    assert "d-i pkgsel/include string htop tmux" in body


def test_preseed_late_command_contains_runcmd():
    body = generate_preseed(_basic_profile())[0].contents
    assert "preseed/late_command" in body
    assert "echo hello" in body


def test_preseed_static_network():
    p = _basic_profile()
    p.network = NetworkConfig(
        hostname="h", dhcp=False, static_ip="192.168.1.10/24",
        gateway="192.168.1.1", dns=["8.8.8.8"],
    )
    body = generate_preseed(p)[0].contents
    assert "get_ipaddress string 192.168.1.10" in body
    assert "get_gateway string 192.168.1.1" in body
    assert "get_nameservers string 8.8.8.8" in body


# ---------------------------------------------------------------------------
# Kickstart
# ---------------------------------------------------------------------------


def test_kickstart_single_file_with_expected_keys():
    files = generate_kickstart(_basic_profile())
    assert len(files) == 1
    body = files[0].contents
    assert body.startswith("# AgentBoot-generated ks.cfg")
    assert f"rootpw --iscrypted {FAKE_HASH}" in body
    assert "user --name=admin" in body
    assert "--groups=wheel" in body  # sudo=True
    assert "timezone Europe/Madrid --utc" in body
    assert "%packages" in body and "%end" in body


def test_kickstart_ssh_keys_emitted():
    body = generate_kickstart(_basic_profile())[0].contents
    assert "sshkey --username=admin" in body
    assert "ssh-ed25519 AAAA..." in body


def test_kickstart_post_section_has_runcmd():
    body = generate_kickstart(_basic_profile())[0].contents
    assert "%post" in body
    assert "echo hello > /tmp/boot.log" in body


def test_kickstart_lvm_mode():
    p = _basic_profile()
    p.disk.use_lvm = True
    body = generate_kickstart(p)[0].contents
    assert "autopart --type=lvm" in body


# ---------------------------------------------------------------------------
# Windows unattend
# ---------------------------------------------------------------------------


def test_windows_unattend_requires_plaintext_password():
    p = _basic_profile()  # only has password_hash
    with pytest.raises(ValueError, match="plaintext"):
        generate_windows_unattend(p)


def test_windows_unattend_produces_wellformed_xml():
    user = User(username="admin", password="s3cr3t")
    p = InstallProfile(user=user, network=NetworkConfig(hostname="win-box"))
    files = generate_windows_unattend(p)
    assert files[0].path == "Autounattend.xml"
    tree = ET.fromstring(files[0].contents)
    ns = "{urn:schemas-microsoft-com:unattend}"
    assert tree.tag == f"{ns}unattend"
    # ComputerName shows up in the specialize pass
    names = [el.text for el in tree.iter(f"{ns}ComputerName")]
    assert "win-box" in names


def test_windows_unattend_restrictive_mode_bits():
    user = User(username="a", password="b")
    p = InstallProfile(user=user)
    files = generate_windows_unattend(p)
    assert files[0].mode == 0o600  # password in plaintext → restrict reads


def test_windows_unattend_escapes_xml_entities():
    user = User(username="ad<m>in", password="p&w\"d")
    p = InstallProfile(user=user)
    body = generate_windows_unattend(p)[0].contents
    # Must not contain the raw unescaped < > & " — anywhere that could
    # break XML parsing.
    tree = ET.fromstring(body)
    assert tree is not None  # parses cleanly


def test_windows_unattend_maps_iana_timezone():
    user = User(username="a", password="b")
    p = InstallProfile(user=user, timezone="Europe/Madrid")
    body = generate_windows_unattend(p)[0].contents
    assert "Romance Standard Time" in body


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def test_generate_for_os_ubuntu_uses_cloud_init():
    files = generate_for_os("ubuntu-server-2404", _basic_profile())
    assert any(f.path.endswith("user-data") for f in files)


def test_generate_for_os_debian_uses_preseed():
    files = generate_for_os("debian-12", _basic_profile())
    assert files[0].path == "preseed.cfg"


def test_generate_for_os_prefix_match():
    # "ubuntu-server-2204" should fall through to the ubuntu-server prefix.
    files = generate_for_os("ubuntu-server-2204", _basic_profile())
    assert any(f.path.endswith("user-data") for f in files)


def test_generate_for_os_unknown_raises():
    with pytest.raises(KeyError):
        generate_for_os("solaris-11", _basic_profile())
