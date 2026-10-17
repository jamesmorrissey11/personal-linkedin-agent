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
