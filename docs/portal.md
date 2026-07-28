# Portal Dashboard 使用指南

ML Platform Blueprint 不再只有 API。`portal/` 提供統一的 ML Platform
Command Center，將模型訓練、版本、promotion、canary、rollback、inference、
observability 與 reviewed GPU evidence 放在同一個操作介面。

## 兩種資料模式

Portal 右上角可切換兩種模式：

- **Demo**：使用明確標示的示範資料與 repository 內的 reviewed evidence。
  適合公開作品展示，不會改變任何平台狀態。
- **Live**：所有平台操作由 Portal 的 server-side BFF 轉送至 Platform API
  與 vLLM。後端位址與 token 不會送到瀏覽器。

公開部署預設使用 Demo，因為公開網站不能、也不應該控制你電腦上的
`localhost`。本機 Docker Compose 則會自動設定 Live 所需的後端位址。

## 最快啟動完整本機平台

需求：Docker Desktop 與 Docker Compose。

```powershell
Copy-Item .env.example .env
# 修改 .env 內的本機密碼。
docker compose up --build --detach
docker compose ps
```

接著開啟：

| 介面 | URL | 用途 |
|---|---|---|
| Portal | <http://127.0.0.1:3001> | 統一操作入口 |
| Platform API | <http://127.0.0.1:8080/docs> | OpenAPI 與除錯 |
| MLflow | <http://127.0.0.1:5000> | 實驗、參數與 artifact |
| Grafana | <http://127.0.0.1:3000> | Metrics 與 SLO |
| Prometheus | <http://127.0.0.1:9090> | 時序查詢 |
| MinIO | <http://127.0.0.1:9001> | 本機 artifact storage |

第一次啟動 registry 是空的。可以直接在 Portal 的 Live 模式按
**Train new version**，或先產生一組完整 lifecycle 狀態：

```powershell
docker compose exec platform-api ml-platform --tenant team-a --model churn-risk demo
```

完成後在 Portal 按右上角重新整理，即可看到 models、runs、deployment
與 canary 狀態。

## 啟用 RTX 4080 SUPER LLM Chat

GPU runtime 採獨立 Compose profile，先確認 CUDA passthrough：

```powershell
python scripts/gpu_preflight.py
python -m benchmarks.inference.run_local_gpu --scenario baseline --start-only
```

當 `http://127.0.0.1:8000/health` healthy 後，Portal 的 Live mode
Inference 頁面會透過 BFF 呼叫本機 Qwen vLLM。若 Portal container
無法連到 Docker Desktop host，可在 `.env` 明確設定：

```dotenv
PORTAL_VLLM_API_URL=http://host.docker.internal:8000
```

## 不使用 Docker，只開 Portal

需求：Node.js 22.13 或更新版本。

```powershell
Set-Location portal
Copy-Item .env.example .env.local
npm.cmd ci
npm.cmd run dev
```

開啟 `http://localhost:3000`。沒有啟動 Platform API 時請維持 Demo
mode；若 API 與 vLLM 已分別在 `8080`、`8000`，可切換 Live。

## Portal 內可以做什麼

### Data Scientist

1. 在 **Runs** 建立 training run。
2. 到 **Models** 比較 accuracy、F1、ROC-AUC 與 Brier score。
3. 在 **Deployments** 發出 promotion，檢視 offline gate。
4. 以 canary traffic 測試候選版本，再 finalize 或 rollback。
5. 在 **Inference** 驗證 predictive routing。

### Platform Operator

1. 從 **Command Center** 查看 readiness、active canary 與近期 audit。
2. 使用 **Observability** 進入 Grafana、Prometheus、MLflow 或 MinIO。
3. 發生異常時在 **Deployments** rollback。
4. 到 **Audit & Runbooks** 核對 actor、reason 與對應處理程序。

### Application Developer

- 使用 **Inference / Predictive** 測試六個 churn features。
- 使用 **Inference / Generative** 呼叫本機 RTX 4080 SUPER vLLM。
- 需要程式整合時再使用 `http://127.0.0.1:8080/docs` 的 API contract。

### Reviewer

- **Evidence** 頁呈現三個正式 GPU scenario、900 個 measured requests、
  zero-error gates、image/model revision 與測試限制。
- Demo 數據、reviewed evidence 與 live telemetry 在 UI 內都有明確標示，
  不會把歷史 benchmark 假裝成即時監控。

## Portal 對應的 API

Portal 新增的 discovery endpoints：

- `GET /v1/tenants`
- `GET /v1/tenants/{tenant}/overview`
- `GET /v1/tenants/{tenant}/models`
- `GET /v1/tenants/{tenant}/runs`
- `GET /v1/tenants/{tenant}/runs/{run_id}`
- `GET /v1/tenants/{tenant}/models/{model}/deployment/history`

Lifecycle mutation 仍使用既有的 train、promotion、finalize、rollback 與
predict endpoints。Portal BFF 只允許固定後端 base URL，並限制會轉送的
headers；LLM chat 另有 message length、timeout 與 output token 上限。

## 誠實邊界

- Demo mode 的 models、runs、audit 與一般 observability cards 是示範資料。
- Evidence 頁的 RTX 4080 SUPER 數據來自 reviewed JSON snapshot，不是 live
  GPU exporter。
- 目前 authentication 與 tenant identity 是 reference contract，尚未接
  OIDC。不要把本機 profile 當成公開 production control plane。
- Reference training API 是同步執行；production blueprint 會把相同 contract
  交給 Kubeflow Pipelines 與 Kueue。
