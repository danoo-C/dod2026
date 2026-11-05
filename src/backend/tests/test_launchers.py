"""./dod (WSL) and dod.bat (Windows, windows/dod.ps1) have the same commands;
the Windows scripts stay readable by Windows PowerShell 5.1 (ASCII)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOD = (ROOT / "dod").read_text(encoding="utf-8")
PS1 = (ROOT / "windows" / "dod.ps1").read_text(encoding="utf-8")


def bash_commands():
    """The labels of ./dod's last `case "$1" in`: the commands that run something."""
    body = DOD[DOD.rindex('case "$1" in'):]
    return {m for m in re.findall(r"^    ([a-z][a-z-]*)\)$", body, re.M)}


def ps1_list(name):
    m = re.search(r"\$" + name + r" = @\(([^)]*)\)", PS1)
    assert m, name
    return set(re.findall(r'"([^"]+)"', m[1]))


def help_commands(text):
    """The first word of each command line in a --help text."""
    return set(re.findall(r"^  ([a-z][a-z-]*)(?: |$)", text, re.M))


def test_the_same_commands():
    assert bash_commands() | {"build"} == ps1_list("Commands")  # ./dod handles build before its case


def test_the_same_hcl_tools_and_esp_commands():
    bash_tools = set(re.search(r"HCL_TOOLS=\(([^)]*)\)", DOD)[1].split())
    assert bash_tools == ps1_list("HclTools")
    for sub in ("upload", "run", "repl"):
        assert f"{sub})" in DOD and f'"{sub}"' in PS1


def test_the_same_help():
    bash_help = DOD[DOD.index("show_help() {"):DOD.index("show_manual() {")]
    ps1_help = PS1[PS1.index("function Show-Help {"):PS1.index("function Show-Manual {")]
    assert help_commands(bash_help) == help_commands(ps1_help)
    assert help_commands(bash_help) >= bash_commands() | {"build"}


def test_the_windows_manual_is_read_from_dod():
    # dod.ps1 prints ./dod's manual, found by this pattern
    assert re.search(r"(?s)show_manual\(\) \{\s*cat <<'EOF'\r?\n(.*?)\r?\nEOF", DOD)


def test_the_windows_scripts_are_ascii():
    for path in [ROOT / "dod.bat", ROOT / "start.bat", *sorted((ROOT / "windows").glob("*.ps1")),
                 ROOT / "src" / "hcl" / "bridge" / "serial-bridge.ps1"]:
        data = path.read_bytes()
        assert data.isascii(), f"{path.name}: Windows PowerShell 5.1 would misread it"
