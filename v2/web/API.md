# MVP-2.1 Local Demo API

Local-only FastAPI endpoints:

- `GET /api/health`
- `GET /api/scenarios`
- `POST/GET /api/sessions`
- `POST/GET /api/tasks`
- `GET /api/tasks/{id}/events|context|actions|progress|stream`
- `POST /api/tasks/{id}/resume`

`POST /api/tasks` accepts `session_id`, `goal`, `scenario` (`normal`, `timeout`, `repeated_final`, `long_context`) and `scenario_id` (`F001`, `F323`). All scenarios are synthetic and use a controlled mock model driver through the real Runtime/Harness. No endpoint executes shell commands or accesses real vehicles.
