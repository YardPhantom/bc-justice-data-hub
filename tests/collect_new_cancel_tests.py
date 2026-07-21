from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_collect_new_uses_powershell_runner():
    cmd = (ROOT / 'tools' / 'collect-new.cmd').read_text(encoding='utf-8').lower()
    assert 'collect-new.ps1' in cmd
    assert 'start "" /wait /b powershell.exe' in cmd


def test_cancel_prompt_is_single_key():
    ps1 = (ROOT / 'tools' / 'collect-new.ps1').read_text(encoding='utf-8')
    assert '[Console]::ReadKey($true)' in ps1
    assert 'Stop Collect New? Press Y for Yes or N for No:' in ps1
    assert 'PipelineStoppedException' in ps1


def test_menu_uses_powershell_runner():
    menu = (ROOT / 'command.cmd').read_text(encoding='utf-8').lower()
    assert 'if "%choice%"=="2" powershell.exe' in menu
    assert 'tools\\collect-new.ps1' in menu
