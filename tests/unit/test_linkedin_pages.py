import pytest

import tests.playwright.helpers  # noqa: F401  (placeholder Azure env vars so the managers import)
from linkedin_pages import LinkedInBusyError, linkedin_lock
from tests.async_helpers import run_async_test


def test_second_lock_holder_times_out(tmp_path):
    async def scenario():
        async with linkedin_lock(5, tmp_path / "l.lock"):
            with pytest.raises(LinkedInBusyError):
                async with linkedin_lock(1.5, tmp_path / "l.lock"):
                    pass

    run_async_test(scenario)


def test_lock_is_released_after_exit(tmp_path):
    async def scenario():
        async with linkedin_lock(1, tmp_path / "l.lock"):
            pass
        async with linkedin_lock(1, tmp_path / "l.lock"):
            return True

    assert run_async_test(scenario) is True


def test_managers_reexport_moved_helpers():
    import inbox_manager
    import invitations_manager
    import linkedin_pages

    assert invitations_manager.get_invitation_info is linkedin_pages.get_invitation_info
    assert inbox_manager.extract_conversation_messages is linkedin_pages.extract_conversation_messages


def test_open_linkedin_passes_approval_to_the_guard(tmp_path, monkeypatch):
    import linkedin_pages
    from linkedin_guard import ApprovedAction

    installed = []

    class FakePage:
        url = "https://www.linkedin.com/feed/"

        async def goto(self, url):
            pass

    class FakeContext:
        async def new_page(self):
            return FakePage()

    class FakeBrowser:
        async def new_context(self, storage_state):
            return FakeContext()

        async def close(self):
            pass

    class FakeChromium:
        async def launch(self, headless):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def fake_install(context, approval=None):
        installed.append(approval)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(linkedin_pages, "async_playwright", FakePlaywright)
    monkeypatch.setattr(linkedin_pages, "install_linkedin_write_guard", fake_install)
    approval = ApprovedAction("message", "send")

    async def scenario():
        async with linkedin_pages.open_linkedin(headless=True, unattended=True, approval=approval, lock_timeout=1):
            pass
        async with linkedin_pages.open_linkedin(headless=True, unattended=True, lock_timeout=1):
            pass

    run_async_test(scenario)
    assert installed == [approval, None]
