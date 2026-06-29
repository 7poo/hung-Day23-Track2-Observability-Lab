# Hướng dẫn hoàn thiện Day 23 — Track 2 Observability Lab

Tài liệu này đi theo đúng thứ tự `00` → `05`, giải thích **làm gì**, **vì sao làm**, **kết quả phải thấy** và **bằng chứng cần lưu**. Các lệnh `make` bên dưới được chạy tại thư mục gốc của lab.

> Trên Windows, nên chạy toàn bộ lệnh trong **WSL2 Ubuntu**. `Makefile` dùng `/bin/bash`, `curl`, `grep` và shell script nên không chạy nguyên vẹn trong PowerShell thuần.

## 1. Đích đến của lab

Sau khi hoàn thiện, luồng observability có dạng:

```text
Người dùng/Locust
       |
       v
FastAPI inference-api
  | metrics --------------> Prometheus ----> Alertmanager ----> Slack
  |                              |
  | traces --> OTel Collector --> Jaeger
  |                              |
  ` logs ----------------------> Loki
                                 |
                         Grafana (một nơi để xem)

Baseline data + Current data --> PSI/KL/KS --> drift-summary/report
Các lab Day 16-22 -----------> Prometheus --> Cross-Day dashboard
```

Ý nghĩa tổng thể: metrics cho biết **có vấn đề hay không**, traces cho biết **chậm/hỏng ở công đoạn nào**, logs cho biết **sự kiện cụ thể là gì**, còn drift cho biết **dữ liệu hoặc chất lượng mô hình đã đổi theo thời gian hay chưa**.

## 2. Chuẩn bị trước khi chạy

### 2.1. Yêu cầu

- Docker Desktop đang chạy, dùng Docker Compose v2.
- WSL2 đã bật và Docker Desktop đã bật integration với distro WSL.
- Tối thiểu khoảng 4 GB RAM trống; khuyến nghị 6–8 GB.
- Python 3.12 hoặc 3.13 cho các script chính.
- Python 3.12 riêng cho Evidently 0.4.40.
- Các cổng `3000`, `3100`, `4317`, `4318`, `8000`, `8888`, `9090`, `9093`, `16686` chưa bị chiếm.

Kiểm tra nhanh trong PowerShell:

```powershell
wsl --status
docker version
docker compose version
pwsh .\00-setup\windows-setup.ps1
```

Sau đó mở WSL và đi tới repo (đổi đường dẫn nếu cần):

```bash
cd /mnt/c/Users/Admin/Downloads/hung-Day23-Track2-Observability-Lab
```

### 2.2. Tạo môi trường Python

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Ý nghĩa: cô lập dependency của lab khỏi Python hệ thống. `locust`, `requests`, `numpy`, `scipy`, `pandas` và `pyarrow` đều được các bước sau sử dụng.

### 2.3. Cấu hình biến môi trường

```bash
cp -n .env.example .env
nano .env
```

Điền ít nhất:

```dotenv
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
GRAFANA_ADMIN_PW=admin
```

Không commit `.env` vì webhook là secret. Tạo trước hai channel Slack `#observability` và `#oncall`, hoặc sửa tên channel trong `02-prometheus-grafana/alertmanager/alertmanager.yml` cho phù hợp workspace.

## 3. Step 00 — Pre-flight và dựng stack

### Mục tiêu

Phát hiện lỗi môi trường trước khi debug ứng dụng: Docker daemon, tài nguyên, cổng và image. Đây là lớp “health của nền tảng”; nếu lớp này sai thì mọi lỗi dashboard phía sau chỉ là triệu chứng.

### Thực hiện

```bash
make setup
```

Nếu `make setup` gặp lỗi shell trên Windows, chạy các phần tương đương:

```bash
cp -n .env.example .env
pip install -r requirements.txt
bash 00-setup/pull-images.sh
python 00-setup/verify-docker.py
```

Khởi động 7 service:

```bash
make up
docker compose ps
```

Chờ khoảng 30 giây rồi kiểm tra:

```bash
make smoke
```

Kết quả đúng là cả 7 service đều `OK`:

- `app`: API mô phỏng inference.
- `prometheus`: thu thập time-series metrics và tính alert rules.
- `alertmanager`: gom nhóm, route và gửi cảnh báo.
- `grafana`: trực quan hóa metrics/logs/traces.
- `loki`: kho logs.
- `jaeger`: kho và giao diện distributed traces.
- `otel-collector`: cổng nhận telemetry, xử lý sampling rồi export.

### Bằng chứng cần lưu

- File `00-setup/setup-report.json` do `verify-docker.py` sinh ra.
- Output `docker compose ps` hoặc `make smoke` để điền vào `submission/REFLECTION.md`.

### Khi lỗi

```bash
docker compose ps
docker compose logs --tail=100 <ten-service>
```

Ví dụ `docker compose logs --tail=100 alertmanager`. Không dùng `make clean` trừ khi muốn xóa cả dữ liệu Prometheus/Grafana đã lưu.

## 4. Step 01 — Instrument FastAPI

### Mục tiêu

Biến một service “chỉ chạy được” thành một service “đo được”. App phát ra ba nhóm tín hiệu:

| Tín hiệu | Metric/span | Ý nghĩa |
|---|---|---|
| Rate | `inference_requests_total` | Lưu lượng và số request thành công/lỗi |
| Errors | label `status="error"` | Tỷ lệ thất bại |
| Duration | `inference_latency_seconds_bucket` | Phân phối latency để tính P50/P95/P99 |
| Saturation | `inference_active_gauge` | Số request đang xử lý |
| Resource | `gpu_utilization_percent` | Mức sử dụng GPU mô phỏng |
| AI/LLM | `inference_tokens_total` | Token input/output, nền tảng để tính cost |
| AI quality | `inference_quality_score` | Chất lượng model dưới dạng production metric |
| Trace spans | `embed-text`, `vector-search`, `generate-tokens` | Thời gian từng công đoạn trong pipeline |

RED là Rate–Errors–Duration, phù hợp với service. USE là Utilization–Saturation–Errors, phù hợp với tài nguyên. AI service cần thêm token, cost và quality vì HTTP 200 chưa có nghĩa câu trả lời tốt.

### Tạo request và kiểm tra metrics

```bash
curl -s http://localhost:8000/healthz

curl -s -X POST http://localhost:8000/predict \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Observability giúp ích gì?","model":"llama3-mock"}'

curl -s http://localhost:8000/metrics | grep -E \
  'inference_requests_total|inference_latency_seconds_bucket|inference_active_gauge|gpu_utilization_percent|inference_tokens_total|inference_quality_score'
```

Kết quả đúng: response `/predict` có text, token count, quality và `trace_id`; `/metrics` có đủ 6 metric family được rubric yêu cầu.

`inference_active_gauge` thường đã về `0` khi xem thủ công vì request đã hoàn thành. Ở Step 02, quan sát metric này trong lúc Locust chạy để thấy nó tăng rồi trở về 0.

### Lưu ý cần hoàn thiện trong source trace

Trong bản repo hiện tại, `predict` được tạo bằng `tracer.start_span("predict")` nhưng không đưa span này vào current context. Vì vậy ba manual span có thể không trở thành con của `predict`, và `trace_id` trả về có thể khác trace của FastAPI server span.

Để đạt checkpoint “một trace có 3 child spans”, nên refactor `predict()` dùng:

```python
with tracer.start_as_current_span("predict") as span:
    # embed-text, vector-search và generate-tokens nằm trong block này
    ...
```

Không gọi `span.end()` thủ công khi dùng context manager. Sau khi sửa:

```bash
docker compose up -d --build app
```

Ý nghĩa của sửa đổi: OpenTelemetry xác định quan hệ cha–con qua **current context**, không phải chỉ qua việc các span được tạo gần nhau trong code.

### Bằng chứng cần lưu

- Output `/metrics` có đủ metric.
- Screenshot panel active requests trong khi chạy load.
- Trace và log sẽ lưu ở Step 03.

## 5. Step 02 — Prometheus, Grafana, SLO và Alertmanager

### Mục tiêu

Đi từ telemetry thô tới vận hành:

1. Prometheus scrape `/metrics` mỗi 15 giây.
2. PromQL biến counter/histogram thành RPS, error rate, percentile và cost.
3. Grafana trình bày thành dashboard-as-code.
4. Alert rules chuyển triệu chứng thành hành động.
5. Alertmanager gom nhóm, chống spam và gửi fire/resolve tới Slack.

### 5.1. Kiểm tra scrape target

Mở <http://localhost:9090/targets>. Target `inference-api` phải có state `UP`.

Có thể kiểm tra bằng API:

```bash
curl -s http://localhost:9090/api/v1/query \
  --data-urlencode 'query=up{job="inference-api"}'
```

Ý nghĩa của `up=1`: Prometheus gọi được endpoint metrics. Nó không khẳng định model trả lời đúng; vì vậy lab còn quality metric, traces và drift.

### 5.2. Sinh tải

```bash
make load
```

Lệnh tạo 10 user đồng thời, tăng 2 user/giây và chạy 60 giây. Trong lúc chạy, mở Grafana <http://localhost:3000>, đăng nhập `admin/admin`, chọn folder **AICB Day 23**.

Kiểm tra ba dashboard:

- AI Service Overview: RPS, latency percentile, error, GPU, token, cost.
- SLO Burn Rate: tốc độ tiêu error budget.
- Cost and Tokens: throughput token và chi phí ước tính.

Chọn time range `Last 15 minutes`, refresh `5s`. Nếu panel rỗng, kiểm tra target `UP`, chạy lại load và đảm bảo time range bao phủ thời điểm vừa chạy.

Ý nghĩa percentile: P99 = 500 ms nghĩa là 99% request không chậm hơn 500 ms; đây không phải average. Histogram bucket cho phép Prometheus ước lượng percentile bằng `histogram_quantile`.

### 5.3. Hiểu SLO burn rate

SLO của lab là 99.5% request thành công, nên error budget là `0.5%`.

```text
failure rate quan sát được
burn rate = --------------------------
                 0.005
```

- Burn rate `1`: tiêu budget đúng kế hoạch.
- Burn rate `14.4`: tiêu budget nhanh gấp 14.4 lần.
- Hai cửa sổ ngắn+dài cùng vượt ngưỡng giúp phát hiện sự cố nhanh nhưng giảm cảnh báo do spike ngắn.

Recording rule cửa sổ `1h` và `6h` cần đủ dữ liệu để có ý nghĩa. Trong một buổi lab mới khởi động, panel dài hạn có thể trống hoặc chưa ổn định; đây là hành vi bình thường của range vector.

### 5.4. Kích hoạt ServiceDown

Trước tiên kiểm tra rules tại <http://localhost:9090/rules> và Alertmanager tại <http://localhost:9093>.

```bash
make alert
```

Script dừng `day23-app`, chờ Prometheus scrape fail và rule `for: 1m` đủ thời gian, sau đó start app và chờ resolve.

Thực tế mong đợi ở kịch bản này là **ServiceDown**. `HighInferenceLatency` không nhất thiết fire vì khi app bị dừng không còn sample latency mới. Inhibit rule cũng chủ ý chặn warning khi ServiceDown critical đang active.

Chụp ba bằng chứng:

- Alertmanager có `ServiceDown` firing.
- Slack nhận firing.
- Slack nhận resolved sau khi app trở lại.

### 5.5. Bẫy cấu hình Slack

Alertmanager không tự nội suy mọi environment variable trong YAML. Nếu container báo lỗi quanh `{{ env "SLACK_WEBHOOK_URL" }}`, cấu hình webhook theo một trong hai cách an toàn:

1. Sinh một file config cục bộ từ template trước khi start, đặt URL thật vào file đã gitignore; hoặc
2. Dùng trường `api_url_file` và mount một file secret chỉ chứa webhook.

Không ghi webhook thật vào file được commit. Test webhook độc lập:

```bash
curl -X POST -H 'Content-Type: application/json' \
  --data '{"text":"Day 23 webhook test"}' \
  "$SLACK_WEBHOOK_URL"
```

Sau khi đổi config:

```bash
docker compose restart alertmanager
docker compose logs --tail=100 alertmanager
```

## 6. Step 03 — Distributed tracing và logs

### Mục tiêu

Dashboard cho biết P99 tăng; trace chỉ ra thời gian nằm ở embedding, vector search hay generation; log cung cấp dữ kiện của đúng request đó. `trace_id` là khóa để nối ba góc nhìn.

### 6.1. Sinh và tìm trace

Do collector dùng tail sampling, trace khỏe chỉ được giữ 1% và collector chờ 30 giây mới quyết định. Vì vậy cách chắc chắn nhất để kiểm tra là sinh nhiều request hoặc sinh lỗi:

```bash
make load
sleep 35
```

Mở Jaeger <http://localhost:16686>, chọn service `inference-api`, Lookback `Last 1 hour`, bấm **Find Traces**. Trace đạt yêu cầu phải có request `/predict` và các span:

```text
predict
├── embed-text
├── vector-search
└── generate-tokens
```

Mở attributes và chụp các field như:

- `gen_ai.request.model`
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`
- `gen_ai.response.finish_reason`

### 6.2. Ý nghĩa tail sampling

Collector chờ toàn bộ trace rồi áp chính sách:

- giữ 100% trace ERROR;
- giữ 100% trace chậm hơn 2 giây;
- chỉ giữ 1% trace khỏe.

Nếu tỷ lệ error = 1%, slow không-error = 1%, healthy = 98%:

```text
retention = 0.01 × 1 + 0.01 × 1 + 0.98 × 0.01
          = 0.0298 ≈ 3%
```

Ý nghĩa: giảm khoảng 97% chi phí lưu trữ nhưng vẫn giữ tín hiệu có giá trị điều tra cao. Đổi lại collector phải buffer trace trong `decision_wait: 30s` và mọi span của cùng trace phải tới cùng collector.

### 6.3. Trạng thái log → Loki trong repo

Repo hiện tại in JSON log ra stdout, nhưng `otel-config.yaml` chỉ khai báo pipeline `traces` và `metrics`; chưa có `filelog` receiver, `logs` pipeline hoặc Loki exporter. Compose cũng chưa mount Docker log file vào collector. Vì vậy **Loki chạy không đồng nghĩa Loki đã nhận log app**.

Để hoàn thiện checkpoint log correlation, cần thêm một log shipper. Hướng phù hợp là:

- Grafana Alloy đọc Docker logs rồi gửi Loki; hoặc
- OTel Collector `filelog` receiver đọc một volume log dùng chung, sau đó export OTLP HTTP tới Loki.

Sau khi nối pipeline, kiểm tra tại Grafana → Explore → datasource Loki, query label tương ứng với app, mở một JSON log có `trace_id`, rồi bấm derived field **TraceID** để sang Jaeger.

Lưu ý thêm: success log hiện có `trace_id` do code truyền thủ công; error log `forced failure` chưa truyền field này. Nên inject `trace_id`/`span_id` từ current span vào mọi log event bằng một `structlog` processor để correlation nhất quán.

### Bằng chứng cần lưu

- `submission/screenshots/jaeger-trace.png` có đủ ba child spans.
- Screenshot attributes theo GenAI conventions.
- Một JSON log line có `trace_id` và ảnh click từ Loki sang đúng Jaeger trace.
- Phép tính retention tail-sampling trong reflection.

## 7. Step 04 — Drift detection

### Mục tiêu

Metrics hạ tầng có thể xanh trong khi input production đã khác dữ liệu huấn luyện hoặc quality đã giảm. Drift detection so sánh phân phối **reference** và **current**, bổ sung lớp giám sát chất lượng dữ liệu/model.

### 7.1. Chạy báo cáo core

```bash
make drift
```

Hoặc:

```bash
cd 04-drift-detection
python scripts/drift_detect.py
cd ..
```

Script dùng seed cố định, tạo 1.000 dòng baseline và 1.000 dòng current. `prompt_length` và `response_quality` được cố ý shift; `embedding_norm` và `response_length` giữ ổn định.

Kết quả:

- `04-drift-detection/data/reference.parquet`
- `04-drift-detection/data/current.parquet`
- `04-drift-detection/reports/drift-summary.json`
- HTML chỉ sinh khi đã cài Evidently.

Mở summary:

```bash
cat 04-drift-detection/reports/drift-summary.json
```

Ít nhất một feature phải có `"drift": "yes"`; ngưỡng code đang dùng là PSI > 0.2.

### 7.2. Sinh Evidently HTML bằng Python 3.12

Nên dùng venv riêng vì Evidently 0.4.40 yêu cầu NumPy cũ hơn môi trường core:

```bash
python3.12 -m venv .venv-evidently
source .venv-evidently/bin/activate
pip install -r requirements.txt -r requirements-evidently.txt
python 04-drift-detection/scripts/drift_detect.py
```

Mở report trên Windows:

```bash
explorer.exe 04-drift-detection/reports/drift-report.html
```

### 7.3. Ý nghĩa các phép đo

| Phép đo | Dùng tốt khi | Điểm cần nhớ |
|---|---|---|
| PSI | Feature đã chia bin, cần chỉ số dễ giải thích/monitor | Phụ thuộc cách chia bin; thường <0.1 ổn, 0.1–0.2 vừa, >0.2 drift |
| KL divergence | So độ khác của hai phân phối xác suất | Bất đối xứng, nhạy với vùng xác suất gần 0 |
| KS test | Feature số liên tục, không muốn chọn bin | Trả statistic và p-value; p-value còn phụ thuộc sample size |
| MMD | Dữ liệu nhiều chiều như embedding | So phân phối qua kernel; tốn tính toán và cần chọn kernel/bandwidth |

Gợi ý reflection:

- `prompt_length`: KS để phát hiện shift liên tục, PSI để dashboard hóa mức độ.
- `embedding_norm`: KS cho norm 1 chiều; MMD nếu giám sát cả vector embedding.
- `response_length`: KS hoặc PSI theo các bucket có ý nghĩa sản phẩm.
- `response_quality`: KS để phát hiện thay đổi hình dạng; PSI nếu cần alert threshold ổn định.

## 8. Step 05 — Tích hợp các ngày 16–22

### Mục tiêu

Một hệ thống production không chỉ có model API. Dashboard tổng hợp phải trả lời đồng thời: host còn sống không, pipeline có chậm không, lakehouse có job không, vector store có phục vụ không, model server có throughput không và eval có đạt không.

### 8.1. Dùng nguồn thật

Với Qdrant Day 19 và llama.cpp Day 20 chạy trên máy host, bỏ comment các job tương ứng trong `02-prometheus-grafana/prometheus/prometheus.yml`, rồi:

```bash
make restart
```

Prometheus chạy trong container nên `localhost` của nó không phải máy Windows. Trên Docker Desktop, dùng `host.docker.internal:<port>`.

### 8.2. Dùng stub khi không có lab cũ

Mở hai terminal WSL, activate `.venv`, chạy:

```bash
python 05-integration/monitor-day19-vector-store.py
```

```bash
python 05-integration/monitor-day20-llama-cpp.py
```

Hai stub phát metrics ở cổng `9101` và `9102`. Thêm vào `prometheus.yml`:

```yaml
  - job_name: 'day19-stub'
    static_configs:
      - targets: ['host.docker.internal:9101']

  - job_name: 'day20-stub'
    static_configs:
      - targets: ['host.docker.internal:9102']
```

Reload Prometheus mà không xóa dữ liệu:

```bash
curl -X POST http://localhost:9090/-/reload
```

Kiểm tra <http://localhost:9090/targets> và query:

```bash
curl -s http://localhost:9090/api/v1/query \
  --data-urlencode 'query=day19_qdrant_collections'
curl -s http://localhost:9090/api/v1/query \
  --data-urlencode 'query=day20_llamacpp_tokens_per_second'
```

### 8.3. Provision cross-day dashboard

`05-integration/full-stack-dashboard.json` nằm ngoài thư mục Grafana đang mount, nên chưa được auto-load. Copy nó vào thư mục dashboard được provision:

```bash
cp 05-integration/full-stack-dashboard.json \
  02-prometheus-grafana/grafana/dashboards/full-stack-dashboard.json
```

Chờ tối đa 30 giây hoặc restart Grafana:

```bash
docker compose restart grafana
```

Dashboard có 6 panel cho Day 16, 17, 18, 19, 20 và 22. Rubric chấp nhận panel không có source thật hiển thị `No Data`, nhưng ít nhất một nguồn phải có data thật hoặc stub.

## 9. Hoàn thiện submission

Tạo thư mục ảnh nếu chưa có:

```bash
mkdir -p submission/screenshots
```

Checklist file nên có:

```text
00-setup/setup-report.json
04-drift-detection/reports/drift-summary.json
04-drift-detection/reports/drift-report.html
submission/REFLECTION.md
submission/screenshots/dashboard-overview.png
submission/screenshots/slo-burn-rate.png
submission/screenshots/cost-and-tokens.png
submission/screenshots/alertmanager-firing.png
submission/screenshots/slack-firing.png
submission/screenshots/slack-resolved.png
submission/screenshots/jaeger-trace.png
submission/screenshots/jaeger-genai-attributes.png
submission/screenshots/loki-trace-correlation.png
submission/screenshots/cross-day-dashboard.png
```

Điền đủ `submission/REFLECTION.md`. Phần quan trọng nhất là **The single change that mattered most**: nêu một thay đổi cụ thể, bằng chứng trước/sau và liên hệ SLO, cardinality, sampling, correlation hoặc cost—not chỉ viết “em hiểu thêm về observability”.

Ví dụ cấu trúc tốt:

```text
Thay đổi: bỏ label request_id khỏi metric và giữ request_id trong trace/log.
Tác động: số time series giảm mạnh nhưng vẫn điều tra được từng request.
Khái niệm: metric label phải low-cardinality; high-cardinality context thuộc traces/logs.
```

## 10. Verify cuối cùng

Giữ stack đang chạy rồi thực hiện:

```bash
make lint-dashboards
make smoke
make verify
```

`make verify` hiện kiểm tra 12 điều kiện tự động, không bao phủ toàn bộ 100 điểm. Vì vậy exit code 0 là điều kiện cần, chưa phải điều kiện đủ; ảnh chụp, HTML drift, log correlation và nội dung reflection vẫn được chấm thủ công.

Kiểm tra thay đổi trước khi commit:

```bash
git status --short
git diff --check
```

Không commit `.env`, webhook Slack, password hoặc dữ liệu bí mật.

## 11. Bảng URL tra cứu nhanh

| Thành phần | URL | Dùng để làm gì |
|---|---|---|
| FastAPI health | <http://localhost:8000/healthz> | Liveness |
| FastAPI metrics | <http://localhost:8000/metrics> | Metrics thô |
| Prometheus | <http://localhost:9090> | PromQL, targets, rules |
| Alertmanager | <http://localhost:9093> | Alert firing/resolved |
| Grafana | <http://localhost:3000> | Dashboard, Explore, correlation |
| Loki readiness | <http://localhost:3100/ready> | Health của Loki |
| Jaeger | <http://localhost:16686> | Tìm và xem trace |
| OTel self-metrics | <http://localhost:8888/metrics> | Health/throughput collector |

## 12. Thứ tự demo ngắn gọn

Khi cần trình bày lab trong 5–10 phút:

1. `make smoke`: chứng minh stack khỏe.
2. `make load`: Grafana bắt đầu có RPS, latency, token và cost.
3. Mở Prometheus target/rule: giải thích scrape và SLO.
4. `make alert`: cho thấy phát hiện, routing, firing và resolved.
5. Mở Jaeger: đi từ request xuống ba công đoạn con.
6. Từ một log Loki click sang trace: chứng minh correlation.
7. Mở drift report: chứng minh hạ tầng khỏe vẫn chưa đủ cho AI.
8. Mở cross-day dashboard: chứng minh khả năng quan sát xuyên toàn hệ thống.

Kết thúc stack nhưng giữ dữ liệu:

```bash
make down
```

