"""Generators for cloud-init, preseed, kickstart and Windows unattend."""

from __future__ import annotations

from textwrap import dedent, indent
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

from agentboot.autoinstall.profile import (
    GeneratedFile,
    InstallProfile,
    User,
)


# ---------------------------------------------------------------------------
# YAML emission — we avoid PyYAML to keep the core dep-free. Installer
# files are small and structurally simple; a hand-rolled indented emit
# is clearer than dragging a dependency into the install pipeline.
# ---------------------------------------------------------------------------


def _yaml_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    # Quote if the string contains YAML-significant chars or starts/ends
    # with whitespace.
    if any(c in s for c in ":#&*!|>'\"%@`") or s != s.strip() or s == "":
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _yaml_emit(data, indent_level: int = 0) -> str:
    pad = "  " * indent_level
    if isinstance(data, dict):
        if not data:
            return f"{pad}{{}}\n"
        lines = []
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}{k}:")
                lines.append(_yaml_emit(v, indent_level + 1))
            else:
                lines.append(f"{pad}{k}: {_yaml_scalar(v)}")
        return "\n".join(lines) + "\n"
    if isinstance(data, list):
        if not data:
            return f"{pad}[]\n"
        lines = []
        for item in data:
            if isinstance(item, (dict, list)):
                emitted = _yaml_emit(item, indent_level + 1).rstrip()
                # Collapse first line into "- "
                first, *rest = emitted.split("\n", 1)
                first_content = first.lstrip()
                lines.append(f"{pad}- {first_content}")
                if rest:
                    lines.append(rest[0])
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
        return "\n".join(lines) + "\n"
    return f"{pad}{_yaml_scalar(data)}\n"


# ---------------------------------------------------------------------------
# cloud-init (NoCloud / subiquity autoinstall)
# ---------------------------------------------------------------------------


def generate_cloud_init(profile: InstallProfile) -> list[GeneratedFile]:
    """Generate cloud-init ``user-data`` + ``meta-data`` files.

    The ``user-data`` uses the subiquity *autoinstall* schema (Ubuntu
    Server 22.04+) which is a strict superset of generic cloud-init
    v1. Older Ubuntu or plain cloud-init consumers can use the
    ``users:`` / ``runcmd:`` blocks which are format-stable.
    """
    user: User = profile.user
    pwd_hash = user.resolve_password_hash()

    autoinstall: dict = {
        "version": 1,
        "locale": profile.locale,
        "keyboard": {"layout": profile.keyboard},
        "identity": {
            "hostname": profile.network.hostname,
            "username": user.username,
            "password": pwd_hash,
            "realname": user.username,
        },
        "ssh": {
            "install-server": True,
            "allow-pw": user.password_hash is not None or user.password is not None,
            "authorized-keys": list(user.ssh_authorized_keys),
        },
        "timezone": profile.timezone,
        "updates": "security",
        "shutdown": "reboot" if profile.reboot_when_done else "poweroff",
    }

    if profile.packages:
        autoinstall["packages"] = list(profile.packages)

    if profile.runcmd:
        autoinstall["late-commands"] = [
            f"curtin in-target --target=/target -- sh -c {_shell_quote(cmd)}"
            for cmd in profile.runcmd
        ]

    # Storage
    if profile.disk.mode == "wipe":
        storage: dict = {"layout": {"name": "lvm" if profile.disk.use_lvm else "direct"}}
        if profile.disk.target != "auto":
            storage["layout"]["match"] = {"path": profile.disk.target}
        autoinstall["storage"] = storage

    # Network
    net: dict = {"version": 2}
    iface = "eth0"  # cloud-init aliases this to the first NIC
    if profile.network.dhcp:
        net["ethernets"] = {iface: {"dhcp4": True}}
    else:
        cfg = {"dhcp4": False}
        if profile.network.static_ip:
            cfg["addresses"] = [profile.network.static_ip]
        if profile.network.gateway:
            cfg["routes"] = [{"to": "default", "via": profile.network.gateway}]
        if profile.network.dns:
            cfg["nameservers"] = {"addresses": list(profile.network.dns)}
        net["ethernets"] = {iface: cfg}
    autoinstall["network"] = net

    # Caller passthrough
    for k, v in profile.extra_cloud_init.items():
        autoinstall[k] = v

    body = "#cloud-config\nautoinstall:\n" + indent(
        _yaml_emit(autoinstall, 0).rstrip(), "  "
    ) + "\n"

    meta_data = f"instance-id: agentboot-{profile.network.hostname}\n" \
                f"local-hostname: {profile.network.hostname}\n"

    return [
        GeneratedFile(path="nocloud/user-data", contents=body),
        GeneratedFile(path="nocloud/meta-data", contents=meta_data),
    ]


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


# ---------------------------------------------------------------------------
# Debian preseed
# ---------------------------------------------------------------------------


def generate_preseed(profile: InstallProfile) -> list[GeneratedFile]:
    """Generate a ``preseed.cfg`` for debian-installer.

    Follows the syntax documented at
    https://www.debian.org/releases/stable/amd64/apbs04.en.html — one
    ``owner question type value`` per line.
    """
    user = profile.user
    pwd_hash = user.resolve_password_hash()
    d = profile.disk
    n = profile.network

    lines: list[str] = [
        "# AgentBoot-generated preseed.cfg",
        "",
        f"d-i debian-installer/locale string {profile.locale}",
        f"d-i keyboard-configuration/xkb-keymap select {profile.keyboard}",
        "",
        "# Networking",
        f"d-i netcfg/get_hostname string {n.hostname}",
        f"d-i netcfg/get_domain string local",
        "d-i netcfg/choose_interface select auto",
    ]
    if not n.dhcp:
        if n.static_ip:
            ip, _, _prefix = n.static_ip.partition("/")
            lines.extend([
                "d-i netcfg/disable_autoconfig boolean true",
                f"d-i netcfg/get_ipaddress string {ip}",
            ])
        if n.gateway:
            lines.append(f"d-i netcfg/get_gateway string {n.gateway}")
        if n.dns:
            lines.append(f"d-i netcfg/get_nameservers string {' '.join(n.dns)}")

    lines += [
        "",
        "# Mirror + apt",
        "d-i mirror/country string manual",
        "d-i mirror/http/hostname string deb.debian.org",
        "d-i mirror/http/directory string /debian",
        "d-i mirror/http/proxy string",
        "",
        "# Clock / time zone",
        f"d-i time/zone string {profile.timezone}",
        "d-i clock-setup/utc boolean true",
        "d-i clock-setup/ntp boolean true",
        "",
        "# User account",
        "d-i passwd/root-login boolean false",
        "d-i passwd/make-user boolean true",
        f"d-i passwd/user-fullname string {user.username}",
        f"d-i passwd/username string {user.username}",
        f"d-i passwd/user-password-crypted password {pwd_hash}",
        "d-i passwd/user-uid string",
        "d-i passwd/user-default-groups string audio cdrom video "
        + ("sudo" if user.sudo else ""),
        "",
        "# Partitioning",
    ]
    if d.mode == "wipe":
        method = "lvm" if d.use_lvm else "regular"
        lines += [
            "d-i partman-auto/method string " + method,
            "d-i partman-auto/choose_recipe select atomic",
            "d-i partman/confirm boolean true",
            "d-i partman/confirm_nooverwrite boolean true",
            "d-i partman-md/confirm boolean true",
            "d-i partman-lvm/confirm boolean true",
            "d-i partman-lvm/confirm_nooverwrite boolean true",
        ]
        if d.target != "auto":
            lines.append(f"d-i partman-auto/disk string {d.target}")
    else:
        lines.append("d-i partman-auto/method string manual  # review in UI")

    lines += [
        "",
        "# Base system + apt",
        "d-i base-installer/kernel/image string linux-image-amd64",
        "",
        "# Package selection",
        "tasksel tasksel/first multiselect standard, ssh-server",
    ]
    if profile.packages:
        lines.append(
            "d-i pkgsel/include string " + " ".join(profile.packages)
        )
    lines += [
        "d-i pkgsel/update-policy select unattended-upgrades",
        "",
        "# Bootloader",
        "d-i grub-installer/only_debian boolean true",
        "d-i grub-installer/with_other_os boolean true",
        "",
    ]

    if profile.runcmd:
        escaped = " && ".join(profile.runcmd)
        lines.append(
            "d-i preseed/late_command string "
            f"in-target sh -c {_shell_quote(escaped)}"
        )

    lines += [
        f"d-i finish-install/reboot_in_progress note",
        "",
        ("d-i cdrom-detect/eject boolean true"
         if profile.reboot_when_done else "d-i debian-installer/exit/halt boolean true"),
    ]

    # Passthrough
    for k, v in profile.extra_preseed.items():
        lines.append(f"{k}  # extra")
        lines.append(str(v))

    return [GeneratedFile(path="preseed.cfg", contents="\n".join(lines) + "\n")]


# ---------------------------------------------------------------------------
# Red Hat kickstart
# ---------------------------------------------------------------------------


def generate_kickstart(profile: InstallProfile) -> list[GeneratedFile]:
    """Generate a Red Hat / Rocky / Alma kickstart file."""
    user = profile.user
    pwd_hash = user.resolve_password_hash()
    d = profile.disk
    n = profile.network

    lines: list[str] = [
        "# AgentBoot-generated ks.cfg",
        "text",
        "",
        f"lang {profile.locale}",
        f"keyboard {profile.keyboard}",
        f"timezone {profile.timezone} --utc",
        "",
        "# Installation source: NetInstall ISO uses the embedded repo by default",
        "# (override via inst.repo= on the kernel cmdline).",
        "",
        f"rootpw --iscrypted {pwd_hash}",
        f"user --name={user.username} --iscrypted --password={pwd_hash} "
        + ("--groups=wheel " if user.sudo else "")
        + f"--shell={user.shell}",
        "",
    ]

    if user.ssh_authorized_keys:
        for key in user.ssh_authorized_keys:
            lines.append(f'sshkey --username={user.username} "{key}"')
        lines.append("")

    # Network
    if n.dhcp:
        lines.append(
            f"network --bootproto=dhcp --device=link --activate "
            f"--hostname={n.hostname}"
        )
    else:
        parts = [
            "network",
            "--bootproto=static",
            "--device=link",
            "--activate",
            f"--hostname={n.hostname}",
        ]
        if n.static_ip:
            ip, _, _prefix = n.static_ip.partition("/")
            parts.append(f"--ip={ip}")
        if n.gateway:
            parts.append(f"--gateway={n.gateway}")
        if n.dns:
            parts.append("--nameserver=" + ",".join(n.dns))
        lines.append(" ".join(parts))

    lines += ["", "# Storage"]
    if d.mode == "wipe":
        disk_tgt = d.target if d.target != "auto" else ""
        lines.append(f"ignoredisk --only-use={disk_tgt or 'auto'}")
        lines.append(f"zerombr")
        lines.append(f"clearpart --all --initlabel" + (f" --drives={disk_tgt}" if disk_tgt else ""))
        if d.use_lvm:
            lines.append("autopart --type=lvm")
        else:
            lines.append(f"autopart --type=plain --fstype={d.filesystem}")
    else:
        lines.append("# Manual partitioning — review in anaconda UI")

    lines += [
        "bootloader --location=mbr",
        "",
        "firstboot --disabled",
        "selinux --enforcing",
        "firewall --enabled --service=ssh",
        "",
        "%packages",
        "@^minimal-environment",
        "openssh-server",
    ]
    for pkg in profile.packages:
        lines.append(pkg)
    lines.append("%end")

    if profile.runcmd:
        lines.append("")
        lines.append("%post --log=/root/ks-post.log")
        for cmd in profile.runcmd:
            lines.append(cmd)
        lines.append("%end")

    if profile.reboot_when_done:
        lines.append("reboot --eject")
    else:
        lines.append("shutdown")

    # Passthrough
    for k, v in profile.extra_kickstart.items():
        lines.append(f"# {k}")
        lines.append(str(v))

    return [GeneratedFile(path="ks.cfg", contents="\n".join(lines) + "\n")]


# ---------------------------------------------------------------------------
# Windows unattend.xml
# ---------------------------------------------------------------------------


_UNATTEND_TEMPLATE = """\
<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend"
          xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-International-Core-WinPE"
               processorArchitecture="amd64"
               publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS">
      <SetupUILanguage><UILanguage>{locale}</UILanguage></SetupUILanguage>
      <InputLocale>{keyboard}</InputLocale>
      <SystemLocale>{locale}</SystemLocale>
      <UILanguage>{locale}</UILanguage>
      <UserLocale>{locale}</UserLocale>
    </component>
    <component name="Microsoft-Windows-Setup"
               processorArchitecture="amd64"
               publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS">
      <DiskConfiguration>
        <Disk wcm:action="add">
          <DiskID>0</DiskID>
          <WillWipeDisk>{wipe}</WillWipeDisk>
          <CreatePartitions>
            <CreatePartition wcm:action="add">
              <Order>1</Order><Size>500</Size><Type>EFI</Type>
            </CreatePartition>
            <CreatePartition wcm:action="add">
              <Order>2</Order><Size>128</Size><Type>MSR</Type>
            </CreatePartition>
            <CreatePartition wcm:action="add">
              <Order>3</Order><Extend>true</Extend><Type>Primary</Type>
            </CreatePartition>
          </CreatePartitions>
        </Disk>
      </DiskConfiguration>
      <ImageInstall>
        <OSImage>
          <InstallTo><DiskID>0</DiskID><PartitionID>3</PartitionID></InstallTo>
        </OSImage>
      </ImageInstall>
      <UserData>
        <AcceptEula>true</AcceptEula>
        <FullName>{username}</FullName>
        <Organization>AgentBoot</Organization>
      </UserData>
    </component>
  </settings>
  <settings pass="specialize">
    <component name="Microsoft-Windows-Shell-Setup"
               processorArchitecture="amd64"
               publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS">
      <ComputerName>{hostname}</ComputerName>
      <TimeZone>{tz_windows}</TimeZone>
    </component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup"
               processorArchitecture="amd64"
               publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS">
      <UserAccounts>
        <LocalAccounts>
          <LocalAccount wcm:action="add">
            <Password><Value>{password}</Value><PlainText>true</PlainText></Password>
            <Name>{username}</Name>
            <Group>Administrators</Group>
            <DisplayName>{username}</DisplayName>
          </LocalAccount>
        </LocalAccounts>
      </UserAccounts>
      <AutoLogon>
        <Password><Value>{password}</Value><PlainText>true</PlainText></Password>
        <Enabled>false</Enabled>
        <Username>{username}</Username>
      </AutoLogon>
      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <NetworkLocation>Work</NetworkLocation>
        <ProtectYourPC>3</ProtectYourPC>
      </OOBE>
{runcmd_block}
    </component>
  </settings>
</unattend>
"""


# Minimal IANA → Windows timezone mapping; covers the common cases.
# Pass extra_unattend["TimeZone"] to override.
_WINDOWS_TZ = {
    "UTC": "UTC",
    "Europe/Madrid": "Romance Standard Time",
    "Europe/London": "GMT Standard Time",
    "Europe/Berlin": "W. Europe Standard Time",
    "Europe/Paris": "Romance Standard Time",
    "America/New_York": "Eastern Standard Time",
    "America/Chicago": "Central Standard Time",
    "America/Denver": "Mountain Standard Time",
    "America/Los_Angeles": "Pacific Standard Time",
    "Asia/Tokyo": "Tokyo Standard Time",
    "Asia/Shanghai": "China Standard Time",
    "Australia/Sydney": "AUS Eastern Standard Time",
}


def generate_windows_unattend(profile: InstallProfile) -> list[GeneratedFile]:
    """Generate an ``Autounattend.xml`` for Windows Setup.

    Windows stores the password in plaintext inside the XML; this is
    the file format's limitation, not ours. Callers should treat the
    generated file as sensitive (restrictive permissions, delete
    after install).
    """
    user = profile.user
    if user.password is None and user.password_hash:
        raise ValueError(
            "Windows unattend requires a plaintext password (User.password). "
            "The format does not accept pre-hashed values."
        )
    pwd = user.password or ""

    d = profile.disk
    n = profile.network

    runcmd_block = ""
    if profile.runcmd:
        items = []
        for i, cmd in enumerate(profile.runcmd, 1):
            items.append(
                f'          <SynchronousCommand wcm:action="add">\n'
                f"            <Order>{i}</Order>\n"
                f"            <CommandLine>{xml_escape(cmd)}</CommandLine>\n"
                f"            <RequiresUserInput>false</RequiresUserInput>\n"
                f"          </SynchronousCommand>"
            )
        runcmd_block = (
            "      <FirstLogonCommands>\n"
            + "\n".join(items)
            + "\n      </FirstLogonCommands>"
        )

    tz = profile.extra_unattend.get("TimeZone") or _WINDOWS_TZ.get(profile.timezone, "UTC")
    xml = _UNATTEND_TEMPLATE.format(
        locale=xml_escape(profile.locale.replace("_", "-").split(".")[0]),
        keyboard=xml_escape(profile.keyboard),
        wipe=("true" if d.mode == "wipe" else "false"),
        username=xml_escape(user.username),
        hostname=xml_escape(n.hostname),
        tz_windows=xml_escape(tz),
        password=xml_escape(pwd),
        runcmd_block=runcmd_block,
    )
    return [GeneratedFile(path="Autounattend.xml", contents=xml, mode=0o600)]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


# Dispatch table — the dict is also iterated in insertion order for
# the prefix fallback, so list longer keys first when prefixes would
# otherwise collide.
_DISPATCH = {
    "ubuntu-server": generate_cloud_init,
    "ubuntu": generate_cloud_init,
    "debian": generate_preseed,
    "rhel": generate_kickstart,
    "rocky": generate_kickstart,
    "alma": generate_kickstart,
    "centos": generate_kickstart,
    "fedora": generate_kickstart,
    "kickstart": generate_kickstart,
    "windows-server": generate_windows_unattend,
    "windows": generate_windows_unattend,
}


def generate_for_os(os_id: str, profile: InstallProfile) -> list[GeneratedFile]:
    """Pick the right generator for ``os_id`` and return its output.

    Raises :class:`KeyError` if no generator matches. Callers that
    want to add custom mappings can wrap this function or call the
    specific generator directly.
    """
    key = os_id.lower()
    if key in _DISPATCH:
        return _DISPATCH[key](profile)
    # Try prefix match — e.g. "ubuntu-server-2204" → ubuntu-server cloud-init.
    for prefix, fn in _DISPATCH.items():
        if key.startswith(prefix):
            return fn(profile)
    raise KeyError(
        f"No auto-install generator registered for os_id={os_id!r}. "
        f"Supported: {sorted(_DISPATCH)}"
    )
