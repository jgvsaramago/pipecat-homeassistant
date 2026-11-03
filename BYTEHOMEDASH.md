# ByteHomeDash fork

This fork of [kyvaith/pipecat-homeassistant](https://github.com/kyvaith/pipecat-homeassistant)
carries the changes [ByteHomeDash](https://github.com/jgvsaramago/bytehomedash) needs.
Each change is its own commit on `main`, on top of upstream. Install the add-on from
this repository (`https://github.com/jgvsaramago/pipecat-homeassistant`); its images
are published by `.github/workflows/publish.yml` to
`ghcr.io/jgvsaramago/pipecat-homeassistant` when a `v*` tag is pushed. The add-on
uses the per-architecture images (`{arch}-pipecat-assist`): the workflow's
multi-arch manifest step fails on this fork, and Supervisor doesn't need it.

| Version | Change | Why |
| --- | --- | --- |
| 0.2.3 | Gemini Live native Google Search: flow option `google_search` (default off) adds `{"google_search": {}}` to the session's tools (`ToolsSchema.custom_tools[AdapterType.GEMINI]`, next to the MCP tools). | The add-on's `web_search` step makes a second model call and returns two spoken sentences; ByteHomeDash's own `search_web` MCP tool (OpenAI web search, for pages to show as cards) takes ~8 s. Gemini's built-in search answers "what's the weather tomorrow in …" within the turn. |
| 0.2.4 | Gemini Live: when reconnecting with the session resumption handle fails (`1008 BidiGenerateContent session not found or expired`), `ResilientGeminiLiveLLMService._connection_task_handler` drops the handle and starts a fresh session (history re-seeded from the context), up to 3 tries. | Pipecat raises that error out of its connection task and the service goes silent for good while the satellite's WebSocket stays open: a satellite that stays connected for hours stopped answering after Gemini expired the session about an hour in. |
| 0.2.5 | Usage log (`app/usage_log.py`): `ResilientGeminiLiveLLMService._handle_msg_usage_metadata` records each turn's `usage_metadata`; `VaPipecatProtocol` numbers conversations by wake and keeps the last transcripts; one JSON line per turn in `/data/usage/YYYY-MM.jsonl`; `GET /api/assist/usage` aggregates per day and per conversation. | ByteHomeDash's panel shows the voice assistant's token use (Assistente de voz › Consumo), to see what conversations cost and measure optimisations. |

Turn it on for a flow through the config API (there is no UI toggle):

```sh
curl -s http://<ha>:7860/api/assist/config  # read flows, set "google_search": true on one, PUT {"flows": [...]}
```

Version numbers continue from upstream (0.2.5 = upstream 0.2.2 + the table above);
re-base on upstream and bump past its version when updating.
