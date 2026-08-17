from pathlib import Path

from vaporstep.directory_browser import DirectoryBrowser
from vaporstep.menu import MenuAction


def test_browser_can_enter_directory_and_choose_it(tmp_path: Path):
    child = tmp_path / "Songs"
    child.mkdir()
    browser = DirectoryBrowser(tmp_path)
    labels = [label for label, _ in browser.entries]
    browser.index = labels.index("Songs")
    assert browser.handle(MenuAction.SELECT) is None
    assert browser.current == child.resolve()
    assert browser.index == 0
    assert browser.handle(MenuAction.SELECT) == child.resolve()


def test_browser_hides_dot_directories(tmp_path: Path):
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "visible").mkdir()
    browser = DirectoryBrowser(tmp_path)
    labels = [label for label, _ in browser.entries]
    assert "visible" in labels
    assert ".hidden" not in labels
