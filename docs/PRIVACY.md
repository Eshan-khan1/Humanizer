# Thoth privacy policy

Last updated: August 17, 2026

Thoth is a **local-first writing assistant**. This policy describes how the Chrome extension and companion Thoth.app handle data.

## What we collect

Thoth does **not** create accounts, analytics, ads, or a central cloud of your writing.

The extension may handle:

- **Text you type or select** in editable fields (grammar, rewrite, generate)
- **Settings** (theme, length, tone, complexity, feature toggles)
- **Optional profile fields** you add (name, email, phone, sign-off, notes)
- **Optional API keys** if you choose API mode
- **A local server token** if you enable Thoth.app authentication

Password, payment, and similar sensitive fields are ignored.

## How we use it

Data is used only to provide Thoth’s writing features:

- Grammar suggestions while you type
- Rewrite / generate from a selection or idea
- Saved defaults for emails and sign-offs

We do **not** sell data, build advertising profiles, or use your drafts to train public models.

## Where it goes

**Default:** text is sent only to the Thoth server on your computer (`http://127.0.0.1:8000`) and, when you use Local mode, to Ollama on the same machine.

**Optional API mode:** if you paste an API key, rewrite/generate/humanize requests go through your local Thoth server to the provider you configured (for example OpenAI or Groq). Keys stay in Chrome storage on this device.

**Chrome sync:** only non-profile preferences (theme, toggles, generate defaults) may sync via `chrome.storage.sync`. Profile fields and API keys stay in local storage on this device.

**Native messaging:** Thoth.app may confirm the local server is running. That traffic stays on your computer.

## Sharing

We do not share your data with third parties except:

- The AI provider **you** configure in API mode
- Google Chrome sync for the preference keys listed above

## Retention and control

- Drafts are not stored by Thoth after a request finishes, except settings and profile fields you save.
- Remove profile fields, API keys, or the extension at any time to delete that stored data from Chrome.
- Uninstalling the extension removes extension storage.

## Contact

Questions: [github.com/Eshan-khan1/Thoth/issues](https://github.com/Eshan-khan1/Thoth/issues)
