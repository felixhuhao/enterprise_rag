# Enterprise RAG Frontend

Vue 3 + TypeScript admin console for the Enterprise RAG backend.

## Development

```bash
npm install
npm run dev
```

By default, Vite proxies API requests to `http://localhost:8010`. Override the
target in `frontend/.env` when needed:

```env
VITE_API_TARGET=http://localhost:8010
```

Build:

```bash
npm run build
```

Preview production output:

```bash
npm run preview
```

## Source Layout

```text
src/
├── api/                 # axios client and typed API wrappers
├── components/
│   ├── admin/           # ACL/admin-only views
│   ├── common/          # shared small UI components
│   ├── documents/       # document list, detail, chunk quality
│   ├── evaluate/        # golden-set eval, query stats, run details
│   ├── evaluation/      # legacy/evaluation support components
│   ├── feedback/        # answer feedback views
│   ├── layout/          # app shell and navigation
│   ├── query-chat/      # chat, citations, retrieval trace
│   ├── retrieval-test/  # retrieval-only debugging UI
│   └── settings/        # runtime settings, tags, recent jobs
├── composables/         # reusable Vue composition helpers
├── router/              # route definitions and guards
├── stores/              # Pinia state
├── styles/              # global CSS
└── utils/               # labels, formatting, small helpers
```

## Notes

- API auth uses the bearer token stored by the frontend and sent through
  `src/api/client.ts`.
- SSE chat uses fetch-based streaming; keep auth/error handling in sync with the
  regular API client.
- Arco Design Vue is the base component library.
- Keep mode terminology aligned with backend docs:
  - `retrieval_only` = 仅检索
  - `answer_lite` = 轻答案
  - `full` = 完整
  - 冒烟集 is a case subset, not a separate eval mode.
