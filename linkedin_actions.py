"""Human-approved LinkedIn actions driven by Agent Inbox review graphs."""

COMPOSER_SELECTORS = [
    ".msg-form__contenteditable[contenteditable='true']",
    "div[role='textbox'][aria-label*='Write a message']",
]
SEND_BUTTON_SELECTORS = [
    "button.msg-form__send-button",
    "form button[type='submit']:has-text('Send')",
]
CONVERSATION_MENU_SELECTORS = [
    "main .scaffold-layout__detail button.msg-thread-actions__control",
    "button.msg-thread-actions__control.artdeco-button--2",
]
ARCHIVE_MENU_ITEM_SELECTORS = [
    "[data-view-name='message-toolbar-dropdown-toggle-archive']:has-text('Archive')",
    ".msg-thread-actions__dropdown-option:has-text('Archive')",
]
ARCHIVED_INDICATOR_SELECTORS = [
    "[data-test-messaging-inbox-filters__folder-pill]:has-text('Archived')",
    ".msg-cross-pillar-inbox-filters-v3__drop-down-trigger:has-text('Archived')",
    "[data-view-name='message-toolbar-dropdown-toggle-archive']:has-text('Restore')",
]
