# Day 23 Lab Reflection

**Student:** 7poo
**Submission date:** 2026-06-29
**Lab repo URL:** https://github.com/7poo/hung-Day23-Track2-Observability-Lab.git

---

## 1. Hardware + setup output

Output của `python 00-setup/verify-docker.py` trước/sau khi stack chạy:

```text
Docker:        OK  (29.3.0)
Compose v2:    OK  (5.1.0)
RAM available: 11.51 GB (OK)
Ports free:    BOUND: [9090, 9093, 3000, 3100, 16686, 4317, 4318, 8888]
Report written: C:\Users\Admin\Downloads\hung-Day23-Track2-Observability-Lab\00-setup\setup-report.json
```

Ghi chú: các port 9090/9093/3000/3100/16686/4317/4318/8888 đang `BOUND` vì chính stack lab đang chạy. Port app mặc định 8000 bị một container khác chiếm, nên lab được chạy trên `APP_PORT=8001` và map vào container app port 8000.

---

## 2. Track 02 — Dashboards & Alerts

### 6 essential panels

Dashboard đã được provision vào Grafana và verify tự động tìm thấy 5 dashboard/folder entry, gồm:

- AI Service Overview (`day23-ai-overview`)
- SLO Burn Rate (`day23-slo`)
- Cost & Tokens (`day23-cost-tokens`)
- Cross-Day Stack (`day23-cross-day`)

### Burn-rate panel

SLO dashboard đã load qua provisioning datasource `prometheus` và dùng các metric từ app/Prometheus để theo dõi error budget/burn-rate.

### Alert fire + resolve

| When | What | Evidence |
|---|---|---|
| T0 | stopped `day23-app` | `docker stop day23-app` |
| T0+110s | `ServiceDown` fired | Alertmanager API trả về `ServiceDown active`, `startsAt=2026-06-29 05:19:22 UTC` |
| T1 | restored app | `docker start day23-app` |
| T1+60s | alert resolved | Alertmanager active alert count về `0` |

Slack webhook hiện đang để placeholder trong `.env`, nên Alertmanager fire/resolve đã chạy local nhưng chưa gửi được Slack thật. Để gửi Slack thật chỉ cần thay `SLACK_WEBHOOK_URL` bằng webhook thật rồi restart `day23-alertmanager`.

### One thing surprised me about Prometheus / Grafana

Điều đáng chú ý nhất là dashboard chỉ thật sự hữu ích khi label và datasource được chuẩn hóa từ đầu. Việc thêm `uid: prometheus`/`uid: loki` làm dashboard portable hơn; nếu không, dashboard có thể import thành công nhưng panel lại trống hoặc trỏ sai datasource.

---

## 3. Track 03 — Tracing & Logs

### One trace screenshot from Jaeger

Trace đã kiểm tra trong Jaeger:

- trace id: `9b45a824e6a3415e7c0440e9fb8445d5`
- root span: `predict`
- child spans: `embed-text`, `vector-search`, `generate-tokens`

Ba span con đều có `CHILD_OF` trỏ về span `predict`, nên flow inference đã được biểu diễn đúng theo dạng parent-child.

### Log line correlated to trace

Forced error request dùng để kiểm tra log/trace correlation:

```json
{"model":"llama3-mock","event":"forced failure","level":"error","timestamp":"2026-06-29T05:42:14.747599Z","trace_id":"2c098fc54afcecef096e31ab6ee4e865","span_id":"e3ee9cb0a09d9a65"}
```

Trace id liên quan: `2c098fc54afcecef096e31ab6ee4e865`.

Log được đẩy vào Loki qua OTel logs pipeline, đồng thời app log JSON có `trace_id`/`span_id` để tra ngược sang Jaeger.

### Tail-sampling math

Collector dùng tail-sampling policy:

- giữ 100% trace lỗi (`status_code=ERROR`)
- giữ 100% trace chậm hơn 2s
- giữ 1% healthy trace bằng probabilistic sampling

Kiểm tra thực tế sau decision window:

- forced-error trace `2c098fc54afcecef096e31ab6ee4e865` được giữ trong Jaeger (`jaeger_count=1`)
- healthy trace `817444ba8cd6bf8be71a5df520505e7d` bị drop
- trong batch 20 healthy traces, có 1 trace được giữ (`1/20 = 5%` trong mẫu nhỏ; policy kỳ vọng dài hạn là 1%)

Nếu service tạo 20 traces/sec, với tỷ lệ lỗi 5%, không có slow trace, và healthy sample 1%, số trace giữ lại kỳ vọng là:

```text
20 * 5% * 100% + 20 * 95% * 1%
= 1 + 0.19
= 1.19 traces/sec

fraction kept = 1.19 / 20 = 5.95%
```

Ý nghĩa: tail sampling giúp giữ lại trace có giá trị debug cao, đặc biệt là lỗi/latency cao, thay vì lưu mọi request và làm phình storage.

---

## 4. Track 04 — Drift Detection

### PSI scores

File `04-drift-detection/reports/drift-summary.json`:

```json
{
  "prompt_length": {
    "psi": 3.461,
    "kl": 1.7982,
    "ks_stat": 0.702,
    "ks_pvalue": 0.0,
    "drift": "yes"
  },
  "embedding_norm": {
    "psi": 0.0187,
    "kl": 0.0324,
    "ks_stat": 0.052,
    "ks_pvalue": 0.133853,
    "drift": "no"
  },
  "response_length": {
    "psi": 0.0162,
    "kl": 0.0178,
    "ks_stat": 0.056,
    "ks_pvalue": 0.086899,
    "drift": "no"
  },
  "response_quality": {
    "psi": 8.8486,
    "kl": 13.5011,
    "ks_stat": 0.941,
    "ks_pvalue": 0.0,
    "drift": "yes"
  }
}
```

### Which test fits which feature?

- `prompt_length`: PSI hoặc KS. Đây là numeric distribution dễ bucket theo khoảng độ dài; PSI dễ giải thích cho monitoring định kỳ, KS tốt khi cần test thống kê nhanh.
- `embedding_norm`: KS hoặc PSI. Vì đây là scalar tóm tắt embedding, KS nhạy với dịch chuyển phân phối; nếu muốn dashboard business-friendly thì PSI dễ đọc hơn.
- `response_length`: PSI. Độ dài response thường có bucket tự nhiên và PSI giúp phát hiện output trở nên quá ngắn/quá dài theo thời gian.
- `response_quality`: KS/PSI cho score scalar; nếu dùng embedding hoặc phân phối đa chiều của quality signals thì MMD phù hợp hơn.

---

## 5. Track 05 — Cross-Day Integration

### Which prior-day metric was hardest to expose? Why?

Metric từ Day 20 llama.cpp thường khó hơn vì có thể phụ thuộc runtime/model server thật và naming metric không đồng nhất giữa các deployment. Trong lab này đã dùng stub exporter cho Day 19 vector store và Day 20 llama.cpp, rồi thêm scrape jobs `day19-stub` và `day20-stub` trong Prometheus để Cross-Day dashboard có dữ liệu.

---

## 6. The single change that mattered most

Thay đổi quan trọng nhất là nối metrics, traces và logs bằng cùng một ngữ cảnh quan sát được: app tạo root span `predict`, các bước `embed-text`, `vector-search`, `generate-tokens` trở thành child spans, và log JSON có `trace_id`/`span_id`. Trước đó stack có thể “chạy được”, nhưng khi có lỗi hoặc latency tăng thì vẫn phải đoán nguyên nhân nằm ở embed, vector search hay generate. Sau thay đổi này, một request có thể đi từ Grafana metric → Loki log → Jaeger trace theo cùng trace id.

Điểm này khớp với ý chính của observability: không chỉ thu thập nhiều tín hiệu, mà phải làm chúng liên kết được với nhau để trả lời câu hỏi vận hành. Label/datasource cố định giúp dashboard ổn định, còn trace-context trong log biến log từ dòng text rời rạc thành bằng chứng debug có đường dẫn rõ ràng.
