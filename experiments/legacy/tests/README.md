# Archived v3.3 tests (B4-02)

These tests reference v3.1/v3.2 modules deleted in B4-01a/b/c
(BrowserAgent / Butler / VerticalWorkflows / Domain.AgentTasks /
Storage.Postgres / Storage.Redis / Runtime.Worker / Runtime.Hosting /
Runtime.Device). They are preserved here for git-history continuity
and possible re-use in v3.4+ refactors, but they are **not** part of
the v3.3 test suite.

To re-introduce any of these tests, port them to the v3.3 surface
(McpBrowserRuntime + storage/sqlite/repos.py + GovernedActions) and
move them back to ``Tests/v3/``.

## Mapping (plan §17.3 → archived file)

| Plan entry | Archived |
|---|---|
| `test_butler_*` | butler_chrome_e2e / butler_conversations / butler_governed_chat_loop / butler_service |
| `test_*conversations*` | control_api_conversations / conversations / dashboard_conversations / mcp_conversations |
| `test_vertical_*` | vertical_control_api / vertical_dashboard / vertical_mcp / vertical_workflows |
| `test_personal_shopping` | personal_shopping |
| `test_acceptance_packs` | acceptance_packs |
| `test_agent_planning` / `test_agent_execution` | agent_planning / agent_execution |
| `test_candidate_generation` | candidate_generation |
| `test_browser_agent_*` | browser_agent_backend / coordinator / interactive / lifecycle_control / security |
| `test_browser_write_grants` | browser_write_grants |

Not in the B4-02 plan but referenced from the same legacy stack:
``test_browser_use_installed_integration``, ``test_browser_use_policy_integration``,
``test_browser_session_api``, ``test_control_api``, ``test_dashboard_e2e``,
``test_entrypoints``, ``test_governed_browser_action``, ``test_live_run_control``,
``test_non_idempotent_commit_query``, ``test_redis_streams_integration``,
``test_settings_dashboard_e2e``.

These were also unreachable against the v3.3 source tree and were
left in place pending an explicit B4-02 follow-up.
