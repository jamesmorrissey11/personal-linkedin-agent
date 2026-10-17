import scripts.capture_linkedin_fixtures as capture
from scripts.capture_linkedin_fixtures import sanitize_html
from tests.async_helpers import run_async_test


def test_sanitize_html_replaces_private_text_and_linkedin_urns():
    html = """
    <main>
      <h2>Grace Hopper</h2>
      <p>Can we talk Friday?</p>
      <code>urn:li:fsd_message:(abc,123)</code>
    </main>
    """

    sanitized = sanitize_html(html, {"Grace Hopper", "Can we talk Friday?"})

    assert "Grace Hopper" not in sanitized
    assert "Can we talk Friday?" not in sanitized
    assert "urn:li:" not in sanitized
    assert "[NAME_OR_MESSAGE]" in sanitized
    assert "[LINKEDIN_URN]" in sanitized


def test_open_conversation_menu_uses_visible_selector_match(monkeypatch):
    hidden = FakeElement(visible=False)
    visible = FakeElement(visible=True)
    page = FakePage([hidden, visible])
    clicked = []

    async def fake_safe_click(element):
        clicked.append(element)
        return True

    monkeypatch.setattr(capture, "safe_click", fake_safe_click)

    selector = run_async_test(lambda: capture._open_conversation_menu(page))

    assert selector == capture.CONVERSATION_MENU_SELECTORS[0]
    assert clicked == [visible]


def test_fixture_markup_contains_only_active_thread_and_archive_indicator():
    page = FakePage(
        [],
        locator_values={
            capture.CONVERSATION_DETAIL_SELECTOR: "<section>active thread</section>",
            capture.ARCHIVED_FILTER_SELECTOR: "<button>Archived</button>",
        },
    )

    markup = run_async_test(lambda: capture._fixture_markup(page, include_archived_indicator=True))

    assert "active thread" in markup
    assert "Archived" in markup
    assert "unrelated inbox conversation" not in markup


class FakeElement:
    def __init__(self, *, visible: bool):
        self.visible = visible

    async def is_visible(self):
        return self.visible


class FakeLocator:
    def __init__(self, value):
        self.value = value
        self.first = self

    async def evaluate(self, _expression):
        return self.value


class FakePage:
    def __init__(self, elements, locator_values=None):
        self.elements = elements
        self.locator_values = locator_values or {}

    async def query_selector(self, _selector):
        return self.elements[0]

    async def query_selector_all(self, selector):
        return self.elements if selector == capture.CONVERSATION_MENU_SELECTORS[0] else []

    async def wait_for_timeout(self, _milliseconds):
        pass

    def locator(self, selector):
        return FakeLocator(self.locator_values[selector])
