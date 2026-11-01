"""Generate the Grafana dashboard "Ledgerline / Pipeline" (infra/grafana/dashboards/pipeline.json, ADR 0021).
Edit the panels here and rerun; Grafana picks up the file within a minute. Never edit the JSON by hand.

  uv run python scripts/make_dashboard.py
"""

import json

P = {"type": "prometheus", "uid": "prometheus"}
L = {"type": "loki", "uid": "loki"}
panels, y = [], 0
def ts(title, targets, unit="short", w=12, x=0, h=8, exemplar=False, thresholds=None, desc=""):
    p = {"type": "timeseries", "title": title, "description": desc, "datasource": P, "gridPos": {"h": h, "w": w, "x": x, "y": y},
         "fieldConfig": {"defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 10}}, "overrides": []},
         "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
         "targets": [{"datasource": P, "expr": e, "legendFormat": lf, "refId": chr(65 + i), "exemplar": exemplar} for i, (e, lf) in enumerate(targets)]}
    if thresholds:
        p["fieldConfig"]["defaults"]["thresholds"] = {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "red", "value": thresholds}]}
        p["fieldConfig"]["defaults"]["custom"]["thresholdsStyle"] = {"mode": "line"}
    panels.append(p)
def stat(title, expr, unit, x, w=6, h=4, steps=None, desc="", mappings=None, decimals=None):
    p = {"type": "stat", "title": title, "description": desc, "datasource": P, "gridPos": {"h": h, "w": w, "x": x, "y": y},
         "fieldConfig": {"defaults": {"unit": unit, "thresholds": {"mode": "absolute", "steps": steps or [{"color": "green", "value": None}]},
                                      "mappings": mappings or [], **({"decimals": decimals} if decimals is not None else {})}, "overrides": []},
         "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background", "graphMode": "none"},
         "targets": [{"datasource": P, "expr": expr, "refId": "A", "instant": True}]}
    panels.append(p)
def row(title):
    global y
    panels.append({"type": "row", "title": title, "collapsed": False, "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": []})
    y += 1

row("Service level") 
stat("Within 15 minutes (last 1 h)", "1 - ledgerline:invoice_slow_ratio:rate1h", "percentunit", 0,
     steps=[{"color": "red", "value": None}, {"color": "orange", "value": 0.95}, {"color": "green", "value": 0.99}],
     desc="Share of invoices that reached a terminal status within 15 minutes of upload. SLO: 99% (docs/slo.md).")
stat("Ollama", "max(last_over_time(ledgerline_ollama_up[1m]))", "none", 6, steps=[{"color": "red", "value": None}, {"color": "green", "value": 1}],
     mappings=[{"type": "value", "options": {"0": {"text": "down"}, "1": {"text": "up"}}}], desc="Does Ollama answer? Alert: down for 2 minutes.")
stat("Dead letters (15 min)", "sum(increase(ledgerline_dead_letters_total[15m])) or vector(0)", "none", 12,
     steps=[{"color": "green", "value": None}, {"color": "orange", "value": 1}, {"color": "red", "value": 10}], desc="Alert: more than 10 in 15 minutes.", decimals=0)
stat("Uploads refused (15 min)", "sum(increase(ledgerline_backpressure_rejections_total[15m])) or vector(0)", "none", 18,
     steps=[{"color": "green", "value": None}, {"color": "orange", "value": 1}], desc="429 queue_full: the extraction queue was at MAX_QUEUE_DEPTH.", decimals=0)
y += 4
row("Invoices")
ts("Invoices finished, per minute, by status", [("sum by (status) (rate(ledgerline_invoice_duration_seconds_count[5m])) * 60", "{{status}}")], "short", 12, 0)
ts("Upload → terminal status (p50, p95)", [
    ('histogram_quantile(0.5, sum by (le) (rate(ledgerline_invoice_duration_seconds_bucket[15m])))', "p50"),
    ('histogram_quantile(0.95, sum by (le) (rate(ledgerline_invoice_duration_seconds_bucket[15m])))', "p95")], "s", 12, 12, exemplar=True, thresholds=900,
   desc="Dots are exemplars: click one to open that invoice's trace in Jaeger. The line at 15 minutes is the SLO target.")
y += 8
row("Extraction and the model")
ts("Extraction attempt (p50, p95)", [
    ('histogram_quantile(0.5, sum by (le) (rate(ledgerline_extraction_duration_seconds_bucket[10m])))', "p50"),
    ('histogram_quantile(0.95, sum by (le) (rate(ledgerline_extraction_duration_seconds_bucket[10m])))', "p95")], "s", 12, 0, exemplar=True, thresholds=45,
   desc="Alert: p95 over 45 s for 10 minutes.")
ts("LLM tokens per minute, by model and type", [
    ("sum by (gen_ai_request_model, gen_ai_token_type) (rate(gen_ai_client_token_usage_sum[5m])) * 60", "{{gen_ai_request_model}} {{gen_ai_token_type}}")], "short", 12, 12)
y += 8
ts("Output tokens per second (average)", [("sum by (gen_ai_request_model) (last_over_time(ledgerline_llm_output_speed_per_second_sum[30m])) / sum by (gen_ai_request_model) (last_over_time(ledgerline_llm_output_speed_per_second_count[30m]))", "{{gen_ai_request_model}}")], "short", 8, 0,
   desc="Average over the processes that reported in the last 30 minutes. Built from running totals, not rate(), so one call per process still shows (ADR 0021).")
ts("Model call duration (p50, p95)", [
    ("histogram_quantile(0.5, sum by (le) (rate(gen_ai_client_operation_duration_seconds_bucket[10m])))", "p50"),
    ("histogram_quantile(0.95, sum by (le) (rate(gen_ai_client_operation_duration_seconds_bucket[10m])))", "p95")], "s", 8, 8, exemplar=True)
ts("Waiting for a model slot (p95)", [("histogram_quantile(0.95, sum by (le) (rate(ledgerline_llm_slot_wait_seconds_bucket[10m])))", "p95")], "s", 8, 16,
   desc="Time a job waited for one of LLM_MAX_CONCURRENCY slots.")
y += 8
row("Queues and failures")
ts("Queue depth (ready messages) and the upload limit", [('max by (queue) (last_over_time(ledgerline_queue_depth{queue=~"invoices\\\\..*|erp\\\\..*"}[1m]))', "{{queue}}"), ("max(ledgerline_queue_limit)", "MAX_QUEUE_DEPTH")], "short", 12, 0,
   desc="Alert: extraction queue over 80% of MAX_QUEUE_DEPTH for 5 minutes.")
ts("Dead letters, by job (reasons: the Dead letters page)", [("sum by (task) (increase(ledgerline_dead_letters_total[15m]))", "{{task}}")], "short", 12, 12)
y += 8
row("Logs")
panels.append({"type": "logs", "title": "Logs (click a trace_id to open the trace)", "datasource": L, "gridPos": {"h": 10, "w": 24, "x": 0, "y": y},
               "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending", "enableLogDetails": True},
               "targets": [{"datasource": L, "expr": '{service_name=~"api|worker|relay|erp-mock"}', "refId": "A"}]})
dash = {"uid": "ledgerline-pipeline", "title": "Ledgerline / Pipeline", "tags": ["ledgerline"], "timezone": "browser", "schemaVersion": 41,
        "refresh": "30s", "time": {"from": "now-3h", "to": "now"}, "panels": panels, "editable": True,
        "description": "Invoices from upload to a terminal status: the SLO, extraction and model speed, queues and failures (ADR 0021)."}
json.dump(dash, open("infra/grafana/dashboards/pipeline.json", "w"), indent=2)
print(len(panels), "panels")
