use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use chrono::Utc;
use ed25519_dalek::SigningKey;
use keyring::Entry;
use rand_core::OsRng;
use regex::Regex;
use reqwest::Url;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::{HashMap, HashSet},
    fs,
    io::{BufRead, BufReader},
    path::{Path, PathBuf},
    sync::atomic::{AtomicBool, Ordering},
    time::Duration,
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Manager, RunEvent,
};
use tauri_plugin_autostart::MacosLauncher;
use tauri_plugin_opener::OpenerExt;
use uuid::Uuid;
use walkdir::WalkDir;

const KEYRING_SERVICE: &str = "com.smallink.agent";
const VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Default)]
struct RuntimeState {
    syncing: AtomicBool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AgentConfig {
    platform_url: String,
    agent_id: String,
    display_name: String,
    public_key: String,
    paired_at: String,
    last_seen_at: String,
    codex_authorized: bool,
    codex_cursor: String,
    last_sync: Option<SyncSummary>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct AgentStateView {
    paired: bool,
    platform_url: String,
    agent_id: String,
    display_name: String,
    status: String,
    version: String,
    last_seen_at: String,
    codex_available: bool,
    codex_authorized: bool,
    codex_path: String,
    syncing: bool,
    queued_batches: usize,
    last_sync: Option<SyncSummary>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SyncSummary {
    selected: usize,
    uploaded: usize,
    inserted: usize,
    updated: usize,
    completed_at: String,
    error: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct UploadRecord {
    source: String,
    source_thread_id: String,
    source_container_id: String,
    source_record_id: String,
    raw_type: String,
    raw_label: String,
    raw_text: String,
    summary: String,
    occurred_at: String,
    project_path: String,
    thread_title: String,
    source_uri: String,
    metadata: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct QueueBatch {
    agent_id: String,
    batch_id: String,
    connector_id: String,
    cursor_before: Value,
    cursor_after: Value,
    records: Vec<UploadRecord>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PairResponse {
    ok: bool,
    agent_id: Option<String>,
    token: Option<String>,
    display_name: Option<String>,
    error: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct HeartbeatResponse {
    ok: bool,
    commands: Option<Vec<AgentCommand>>,
    error: Option<String>,
}

#[derive(Debug, Deserialize)]
struct AgentCommand {
    id: String,
    #[serde(rename = "type")]
    command_type: String,
    payload: Value,
}

#[derive(Debug, Deserialize)]
struct UploadResponse {
    ok: bool,
    records: Option<usize>,
    inserted: Option<usize>,
    updated: Option<usize>,
    error: Option<String>,
}

fn app_dir(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map_err(|error| error.to_string())
}

fn config_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app_dir(app)?.join("config.json"))
}

fn queue_dir(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app_dir(app)?.join("queue"))
}

fn log_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app_dir(app)?.join("logs").join("agent.log"))
}

fn ensure_dirs(app: &AppHandle) -> Result<(), String> {
    fs::create_dir_all(queue_dir(app)?).map_err(|error| error.to_string())?;
    fs::create_dir_all(log_path(app)?.parent().unwrap()).map_err(|error| error.to_string())?;
    Ok(())
}

fn read_config(app: &AppHandle) -> Result<Option<AgentConfig>, String> {
    let path = config_path(app)?;
    if !path.exists() {
        return Ok(None);
    }
    let text = fs::read_to_string(path).map_err(|error| error.to_string())?;
    serde_json::from_str(&text)
        .map(Some)
        .map_err(|error| error.to_string())
}

fn write_config(app: &AppHandle, config: &AgentConfig) -> Result<(), String> {
    ensure_dirs(app)?;
    let path = config_path(app)?;
    let text = serde_json::to_string_pretty(config).map_err(|error| error.to_string())?;
    fs::write(&path, format!("{text}\n")).map_err(|error| error.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn credential(name: &str) -> Result<Entry, String> {
    Entry::new(KEYRING_SERVICE, name).map_err(|error| error.to_string())
}

fn get_token() -> Result<String, String> {
    credential("device-token")?
        .get_password()
        .map_err(|_| "设备凭据不可用，请重新配对".to_string())
}

fn append_log(app: &AppHandle, event: &str, detail: Value) {
    if ensure_dirs(app).is_err() {
        return;
    }
    let line = json!({ "at": Utc::now().to_rfc3339(), "event": event, "detail": detail });
    let path = match log_path(app) {
        Ok(path) => path,
        Err(_) => return,
    };
    let mut previous = fs::read_to_string(&path).unwrap_or_default();
    if previous.len() > 10 * 1024 * 1024 {
        previous.clear();
    }
    previous.push_str(&line.to_string());
    previous.push('\n');
    let _ = fs::write(path, previous);
}

fn codex_home(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .home_dir()
        .map(|path| path.join(".codex"))
        .map_err(|error| error.to_string())
}

fn queued_batch_count(app: &AppHandle) -> usize {
    queue_dir(app)
        .ok()
        .and_then(|path| fs::read_dir(path).ok())
        .map(|entries| {
            entries
                .flatten()
                .filter(|entry| {
                    entry.path().extension().and_then(|value| value.to_str()) == Some("json")
                })
                .count()
        })
        .unwrap_or(0)
}

fn state_view(app: &AppHandle, status: &str) -> Result<AgentStateView, String> {
    let config = read_config(app)?.unwrap_or_default();
    let codex_path = codex_home(app)?;
    let paired = !config.agent_id.is_empty() && !config.platform_url.is_empty();
    Ok(AgentStateView {
        paired,
        platform_url: config.platform_url,
        agent_id: config.agent_id,
        display_name: config.display_name,
        status: if paired {
            status.to_string()
        } else {
            "unpaired".to_string()
        },
        version: VERSION.to_string(),
        last_seen_at: config.last_seen_at,
        codex_available: codex_path.is_dir(),
        codex_authorized: config.codex_authorized,
        codex_path: codex_path.to_string_lossy().to_string(),
        syncing: app.state::<RuntimeState>().syncing.load(Ordering::SeqCst),
        queued_batches: queued_batch_count(app),
        last_sync: config.last_sync,
    })
}

fn validate_platform_url(value: &str) -> Result<String, String> {
    let url = Url::parse(value.trim()).map_err(|_| "请输入有效的平台地址".to_string())?;
    let host = url.host_str().unwrap_or_default();
    let local = matches!(host, "127.0.0.1" | "localhost" | "::1");
    if url.scheme() != "https" && !(url.scheme() == "http" && local) {
        return Err("公网平台必须使用 HTTPS".to_string());
    }
    Ok(url.as_str().trim_end_matches('/').to_string())
}

#[tauri::command]
fn get_agent_state(app: AppHandle) -> Result<AgentStateView, String> {
    state_view(&app, "offline")
}

#[tauri::command]
async fn pair_agent(
    app: AppHandle,
    platform_url: String,
    pairing_code: String,
    display_name: String,
) -> Result<AgentStateView, String> {
    if read_config(&app)?.is_some_and(|config| !config.agent_id.is_empty()) {
        return Err("当前设备已经配对，请先解除现有配对".to_string());
    }
    let platform_url = validate_platform_url(&platform_url)?;
    if pairing_code.trim().is_empty() {
        return Err("请输入配对码".to_string());
    }
    let signing_key = SigningKey::generate(&mut OsRng);
    let public_key = BASE64.encode(signing_key.verifying_key().as_bytes());
    let response = reqwest::Client::new()
        .post(format!("{platform_url}/api/agents/pair"))
        .json(&json!({
            "code": pairing_code.trim(),
            "publicKey": public_key,
            "displayName": if display_name.trim().is_empty() { "我的 Mac" } else { display_name.trim() },
            "version": VERSION,
            "operatingSystem": format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH)
        }))
        .send()
        .await
        .map_err(|error| format!("无法连接 Link 平台：{error}"))?
        .json::<PairResponse>()
        .await
        .map_err(|error| format!("配对响应无效：{error}"))?;
    if !response.ok {
        return Err(response.error.unwrap_or_else(|| "配对失败".to_string()));
    }
    let agent_id = response
        .agent_id
        .ok_or_else(|| "平台未返回设备 ID".to_string())?;
    let token = response
        .token
        .ok_or_else(|| "平台未返回设备凭据".to_string())?;
    credential("device-token")?
        .set_password(&token)
        .map_err(|error| format!("设备凭据保存失败：{error}"))?;
    credential("device-signing-key")?
        .set_password(&BASE64.encode(signing_key.to_bytes()))
        .map_err(|error| format!("设备密钥保存失败：{error}"))?;
    let config = AgentConfig {
        platform_url,
        agent_id,
        display_name: response
            .display_name
            .unwrap_or_else(|| display_name.trim().to_string()),
        public_key,
        paired_at: Utc::now().to_rfc3339(),
        ..AgentConfig::default()
    };
    write_config(&app, &config)?;
    append_log(&app, "paired", json!({ "agentId": config.agent_id }));
    heartbeat_once(&app).await
}

#[tauri::command]
fn authorize_codex(app: AppHandle) -> Result<AgentStateView, String> {
    let mut config = read_config(&app)?.ok_or_else(|| "请先连接 Link 平台".to_string())?;
    let path = codex_home(&app)?;
    if !path.is_dir() {
        return Err("没有找到本机 Codex 数据目录".to_string());
    }
    config.codex_authorized = true;
    write_config(&app, &config)?;
    append_log(&app, "codex_authorized", json!({ "path": "~/.codex" }));
    state_view(&app, "online")
}

#[tauri::command]
async fn heartbeat(app: AppHandle) -> Result<AgentStateView, String> {
    heartbeat_once(&app).await
}

async fn heartbeat_once(app: &AppHandle) -> Result<AgentStateView, String> {
    let mut config = read_config(app)?.ok_or_else(|| "请先连接 Link 平台".to_string())?;
    let token = get_token()?;
    let response = reqwest::Client::new()
        .post(format!("{}/api/agents/heartbeat", config.platform_url))
        .bearer_auth(token)
        .json(&json!({
            "agentId": config.agent_id,
            "version": VERSION,
            "operatingSystem": format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH),
            "connectorStates": [{
                "id": "codex_local",
                "status": if config.codex_authorized { "ready" } else { "authorization_required" }
            }]
        }))
        .send()
        .await
        .map_err(|error| format!("平台暂时不可达：{error}"))?
        .json::<HeartbeatResponse>()
        .await
        .map_err(|error| format!("心跳响应无效：{error}"))?;
    if !response.ok {
        return Err(response.error.unwrap_or_else(|| "心跳失败".to_string()));
    }
    config.last_seen_at = Utc::now().to_rfc3339();
    write_config(app, &config)?;
    for command in response.commands.unwrap_or_default() {
        handle_command(app, command).await;
    }
    state_view(app, "online")
}

async fn handle_command(app: &AppHandle, command: AgentCommand) {
    let result = if command.command_type == "sync_connector"
        && command.payload.get("connectorId").and_then(Value::as_str) == Some("codex_local")
    {
        run_sync_guarded(app).await.map(|summary| json!(summary))
    } else if command.command_type == "refresh_config" {
        Ok(json!({ "refreshed": true }))
    } else if command.command_type == "validate_connector" {
        Ok(json!({ "valid": codex_home(app).is_ok_and(|path| path.is_dir()) }))
    } else if command.command_type == "pause_connector" {
        Ok(json!({ "paused": true }))
    } else {
        Err("不支持的指令".to_string())
    };
    if let (Ok(config), Ok(token)) = (read_config(app), get_token()) {
        if let Some(config) = config {
            let (success, payload) = match result {
                Ok(value) => (true, value),
                Err(error) => (false, json!({ "error": error })),
            };
            let _ = reqwest::Client::new()
                .post(format!(
                    "{}/api/agents/commands/complete",
                    config.platform_url
                ))
                .bearer_auth(token)
                .json(&json!({
                    "agentId": config.agent_id,
                    "commandId": command.id,
                    "success": success,
                    "result": payload
                }))
                .send()
                .await;
        }
    }
}

#[tauri::command]
async fn sync_codex(app: AppHandle) -> Result<SyncSummary, String> {
    run_sync_guarded(&app).await
}

async fn run_sync_guarded(app: &AppHandle) -> Result<SyncSummary, String> {
    let runtime = app.state::<RuntimeState>();
    if runtime
        .syncing
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return Err("Codex 正在同步，请稍后查看结果".to_string());
    }
    let result = sync_codex_inner(app).await;
    runtime.syncing.store(false, Ordering::SeqCst);
    if let Err(error) = &result {
        append_log(app, "codex_sync_failed", json!({ "error": error }));
    }
    result
}

async fn sync_codex_inner(app: &AppHandle) -> Result<SyncSummary, String> {
    let mut config = read_config(app)?.ok_or_else(|| "请先连接 Link 平台".to_string())?;
    if !config.codex_authorized {
        return Err("请先确认 Codex 只读授权".to_string());
    }
    append_log(app, "codex_sync_started", json!({}));
    let mut totals = flush_queue(app, &config).await?;
    let records = collect_codex_records(app, &config.codex_cursor)?;
    let selected = records.len();
    let latest = records
        .iter()
        .filter(|record| !record.occurred_at.is_empty())
        .map(|record| record.occurred_at.clone())
        .max()
        .unwrap_or_else(|| config.codex_cursor.clone());
    for chunk in records.chunks(200) {
        let batch = QueueBatch {
            agent_id: config.agent_id.clone(),
            batch_id: format!("codex-{}", Uuid::new_v4()),
            connector_id: "codex_local".to_string(),
            cursor_before: json!({ "latestOccurredAt": config.codex_cursor }),
            cursor_after: json!({ "latestOccurredAt": latest, "syncedAt": Utc::now().to_rfc3339() }),
            records: chunk.to_vec(),
        };
        persist_batch(app, &batch)?;
    }
    let uploaded = flush_queue(app, &config).await?;
    totals.0 += uploaded.0;
    totals.1 += uploaded.1;
    totals.2 += uploaded.2;
    if selected > 0 {
        config.codex_cursor = latest;
    }
    let summary = SyncSummary {
        selected,
        uploaded: totals.0,
        inserted: totals.1,
        updated: totals.2,
        completed_at: Utc::now().to_rfc3339(),
        error: String::new(),
    };
    config.last_sync = Some(summary.clone());
    write_config(app, &config)?;
    append_log(app, "codex_sync_finished", json!(summary));
    Ok(summary)
}

fn persist_batch(app: &AppHandle, batch: &QueueBatch) -> Result<(), String> {
    ensure_dirs(app)?;
    let path = queue_dir(app)?.join(format!("{}.json", batch.batch_id));
    let text = serde_json::to_string(batch).map_err(|error| error.to_string())?;
    fs::write(path, text).map_err(|error| error.to_string())
}

async fn flush_queue(
    app: &AppHandle,
    config: &AgentConfig,
) -> Result<(usize, usize, usize), String> {
    let mut files = fs::read_dir(queue_dir(app)?)
        .map_err(|error| error.to_string())?
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| path.extension().and_then(|value| value.to_str()) == Some("json"))
        .collect::<Vec<_>>();
    files.sort();
    let token = get_token()?;
    let client = reqwest::Client::new();
    let mut totals = (0, 0, 0);
    for path in files {
        let batch: QueueBatch =
            serde_json::from_str(&fs::read_to_string(&path).map_err(|error| error.to_string())?)
                .map_err(|error| error.to_string())?;
        let response = client
            .post(format!(
                "{}/api/agents/ingestion-batches",
                config.platform_url
            ))
            .bearer_auth(&token)
            .json(&batch)
            .send()
            .await
            .map_err(|error| format!("批次上传失败，已保留在本地队列：{error}"))?
            .json::<UploadResponse>()
            .await
            .map_err(|error| format!("批次响应无效：{error}"))?;
        if !response.ok {
            return Err(response.error.unwrap_or_else(|| "批次上传失败".to_string()));
        }
        totals.0 += response.records.unwrap_or(batch.records.len());
        totals.1 += response.inserted.unwrap_or(0);
        totals.2 += response.updated.unwrap_or(0);
        fs::remove_file(path).map_err(|error| error.to_string())?;
    }
    Ok(totals)
}

fn collect_codex_records(app: &AppHandle, cursor: &str) -> Result<Vec<UploadRecord>, String> {
    let home = app.path().home_dir().map_err(|error| error.to_string())?;
    let codex = codex_home(app)?;
    let index = read_session_index(&codex.join("session_index.jsonl"));
    let mut records = Vec::new();
    for directory in [codex.join("sessions"), codex.join("archived_sessions")] {
        if !directory.exists() {
            continue;
        }
        for entry in WalkDir::new(directory).into_iter().flatten() {
            if !entry.file_type().is_file()
                || entry.path().extension().and_then(|value| value.to_str()) != Some("jsonl")
            {
                continue;
            }
            records.extend(parse_session_file(entry.path(), &index, &home, cursor)?);
        }
    }
    records.sort_by(|left, right| left.occurred_at.cmp(&right.occurred_at));
    Ok(records)
}

#[derive(Default)]
struct IndexEntry {
    title: String,
    updated_at: String,
}

fn read_session_index(path: &Path) -> HashMap<String, IndexEntry> {
    let mut index = HashMap::new();
    let Ok(file) = fs::File::open(path) else {
        return index;
    };
    for line in BufReader::new(file).lines().map_while(Result::ok) {
        if let Ok(value) = serde_json::from_str::<Value>(&line) {
            if let Some(id) = value.get("id").and_then(Value::as_str) {
                index.insert(
                    id.to_string(),
                    IndexEntry {
                        title: value
                            .get("thread_name")
                            .and_then(Value::as_str)
                            .unwrap_or("未命名 Codex 线程")
                            .to_string(),
                        updated_at: value
                            .get("updated_at")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                    },
                );
            }
        }
    }
    index
}

fn parse_session_file(
    path: &Path,
    index: &HashMap<String, IndexEntry>,
    home: &Path,
    cursor: &str,
) -> Result<Vec<UploadRecord>, String> {
    let file = fs::File::open(path).map_err(|error| error.to_string())?;
    let rows = BufReader::new(file)
        .lines()
        .map_while(Result::ok)
        .filter_map(|line| serde_json::from_str::<Value>(&line).ok())
        .collect::<Vec<_>>();
    if rows.is_empty() {
        return Ok(Vec::new());
    }
    let meta = rows
        .iter()
        .find(|row| row.get("type").and_then(Value::as_str) == Some("session_meta"))
        .and_then(|row| row.get("payload"))
        .cloned()
        .unwrap_or_else(|| json!({}));
    let fallback_id = path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("unknown")
        .trim_start_matches("rollout-")
        .to_string();
    let session_id = meta
        .get("session_id")
        .or_else(|| meta.get("id"))
        .and_then(Value::as_str)
        .unwrap_or(&fallback_id)
        .to_string();
    let index_entry = index.get(&session_id);
    let title = index_entry
        .map(|entry| entry.title.clone())
        .unwrap_or_else(|| "未命名 Codex 线程".to_string());
    let cwd = clean_text(
        meta.get("cwd").and_then(Value::as_str).unwrap_or_default(),
        home,
    );
    let model = meta
        .get("model")
        .or_else(|| meta.get("model_provider"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let source_uri = clean_text(&path.to_string_lossy(), home);
    let mut updated_at = index_entry
        .map(|entry| entry.updated_at.clone())
        .unwrap_or_default();
    let mut records = Vec::new();
    let mut seen = HashSet::new();
    let mut type_indexes: HashMap<&str, usize> = HashMap::new();
    let mut tool_counts: HashMap<String, usize> = HashMap::new();
    let mut skill_refs = HashSet::new();
    for row in &rows {
        let timestamp = row
            .get("timestamp")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        if timestamp > updated_at {
            updated_at = timestamp.clone();
        }
        let payload = row.get("payload").cloned().unwrap_or_else(|| json!({}));
        let payload_type = payload
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let row_type = row.get("type").and_then(Value::as_str).unwrap_or_default();
        if row_type == "response_item" && payload_type == "message" {
            let role = payload
                .get("role")
                .and_then(Value::as_str)
                .unwrap_or_default();
            let text = text_from_content(payload.get("content"));
            if matches!(role, "user" | "assistant") {
                push_message(
                    &mut records,
                    &mut seen,
                    &mut type_indexes,
                    role,
                    &text,
                    &timestamp,
                    &session_id,
                    &title,
                    &cwd,
                    &source_uri,
                    &model,
                    home,
                    cursor,
                );
            }
        }
        if row_type == "event_msg" && payload_type == "user_message" {
            let text = payload
                .get("message")
                .and_then(Value::as_str)
                .unwrap_or_default();
            push_message(
                &mut records,
                &mut seen,
                &mut type_indexes,
                "user",
                text,
                &timestamp,
                &session_id,
                &title,
                &cwd,
                &source_uri,
                &model,
                home,
                cursor,
            );
        }
        if matches!(payload_type, "function_call" | "custom_tool_call") {
            let name = payload
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            *tool_counts.entry(name.to_string()).or_default() += 1;
            let raw_input = payload
                .get("input")
                .or_else(|| payload.get("arguments"))
                .and_then(Value::as_str)
                .unwrap_or_default();
            skill_refs.extend(extract_skill_refs(raw_input));
            if name == "exec_command" {
                let arguments =
                    serde_json::from_str::<Value>(raw_input).unwrap_or_else(|_| json!({}));
                if let Some(command) = arguments.get("cmd").and_then(Value::as_str) {
                    let index = next_index(&mut type_indexes, "cli");
                    let occurred_at = timestamp.clone();
                    if cursor.is_empty() || occurred_at.is_empty() || occurred_at.as_str() > cursor
                    {
                        let workdir = arguments
                            .get("workdir")
                            .and_then(Value::as_str)
                            .map(|value| clean_text(value, home))
                            .unwrap_or_else(|| cwd.clone());
                        let raw_text = format!(
                            "{}；工作目录：{}",
                            truncate(&clean_text(command, home), 600),
                            workdir
                        );
                        records.push(make_record(
                            &session_id,
                            &title,
                            &workdir,
                            &source_uri,
                            &model,
                            "cli",
                            "CLI",
                            &raw_text,
                            &occurred_at,
                            index,
                            json!({ "command": truncate(&clean_text(command, home), 600) }),
                        ));
                    }
                }
            }
        }
    }
    for (tool_name, count) in tool_counts {
        if cursor.is_empty() || updated_at.is_empty() || updated_at.as_str() > cursor {
            records.push(make_record(
                &session_id,
                &title,
                &cwd,
                &source_uri,
                &model,
                "tool",
                "工具调用",
                &format!("{tool_name} 工具在该线程中调用 {count} 次。"),
                &updated_at,
                next_index(&mut type_indexes, "tool"),
                json!({ "tool_name": tool_name, "tool_count": count }),
            ));
        }
    }
    for skill in skill_refs {
        if cursor.is_empty() || updated_at.is_empty() || updated_at.as_str() > cursor {
            records.push(make_record(
                &session_id,
                &title,
                &cwd,
                &source_uri,
                &model,
                "skill",
                "技能线索",
                &format!("skill:{skill}"),
                &updated_at,
                next_index(&mut type_indexes, "skill"),
                json!({ "skill": skill }),
            ));
        }
    }
    Ok(records)
}

#[allow(clippy::too_many_arguments)]
fn push_message(
    records: &mut Vec<UploadRecord>,
    seen: &mut HashSet<String>,
    type_indexes: &mut HashMap<&str, usize>,
    role: &str,
    text: &str,
    occurred_at: &str,
    session_id: &str,
    title: &str,
    cwd: &str,
    source_uri: &str,
    model: &str,
    home: &Path,
    cursor: &str,
) {
    let cleaned = clean_text(text, home);
    if cleaned.is_empty()
        || (role == "user" && cleaned.starts_with("<environment_context>"))
        || (role == "user" && cleaned.starts_with("<turn_aborted>"))
    {
        return;
    }
    let key = format!("{role}:{}", truncate(&cleaned, 400));
    if !seen.insert(key) || (!cursor.is_empty() && !occurred_at.is_empty() && occurred_at <= cursor)
    {
        return;
    }
    let (raw_type, label) = if role == "user" {
        ("user_input", "Codex 用户消息")
    } else {
        ("codex_output", "Codex 输出")
    };
    records.push(make_record(
        session_id,
        title,
        cwd,
        source_uri,
        model,
        raw_type,
        label,
        &truncate(&cleaned, 1200),
        occurred_at,
        next_index(type_indexes, raw_type),
        json!({}),
    ));
}

#[allow(clippy::too_many_arguments)]
fn make_record(
    session_id: &str,
    title: &str,
    project_path: &str,
    source_uri: &str,
    model: &str,
    raw_type: &str,
    raw_label: &str,
    raw_text: &str,
    occurred_at: &str,
    index: usize,
    metadata: Value,
) -> UploadRecord {
    UploadRecord {
        source: "codex".to_string(),
        source_thread_id: session_id.to_string(),
        source_container_id: session_id.to_string(),
        source_record_id: format!("{session_id}:{raw_type}:{index}:{occurred_at}"),
        raw_type: raw_type.to_string(),
        raw_label: raw_label.to_string(),
        raw_text: raw_text.to_string(),
        summary: truncate(raw_text, 280),
        occurred_at: occurred_at.to_string(),
        project_path: project_path.to_string(),
        thread_title: title.to_string(),
        source_uri: source_uri.to_string(),
        metadata: json!({ "connector": "codex_local", "model": model, "detail": metadata }),
    }
}

fn next_index<'a>(indexes: &mut HashMap<&'a str, usize>, key: &'a str) -> usize {
    let index = indexes.entry(key).or_default();
    let current = *index;
    *index += 1;
    current
}

fn text_from_content(content: Option<&Value>) -> String {
    content
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| {
                    item.get("text")
                        .or_else(|| item.get("output_text"))
                        .and_then(Value::as_str)
                })
                .collect::<Vec<_>>()
                .join("\n")
        })
        .unwrap_or_default()
}

fn clean_text(value: &str, home: &Path) -> String {
    let mut text = value
        .replace('\0', "")
        .replace(&home.to_string_lossy().to_string(), "~");
    if let Ok(secret) =
        Regex::new(r#"(?i)(api[_-]?key|token|password|secret)(["':=\s]+)[^\s"',}]+"#)
    {
        text = secret.replace_all(&text, "$1$2***").to_string();
    }
    if let Ok(api_key) = Regex::new(r"sk-[A-Za-z0-9_-]{12,}") {
        text = api_key.replace_all(&text, "sk-***").to_string();
    }
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn extract_skill_refs(text: &str) -> HashSet<String> {
    let Ok(pattern) = Regex::new(r"(?:^|/)\.codex/skills/([^/\s]+)|/skills/([^/\s]+)/SKILL\.md")
    else {
        return HashSet::new();
    };
    pattern
        .captures_iter(text)
        .filter_map(|capture| capture.get(1).or_else(|| capture.get(2)))
        .map(|value| value.as_str().to_string())
        .collect()
}

fn truncate(value: &str, limit: usize) -> String {
    let mut chars = value.chars();
    let result = chars.by_ref().take(limit).collect::<String>();
    if chars.next().is_some() {
        format!("{result}...")
    } else {
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn platform_url_allows_local_http_and_public_https() {
        assert_eq!(
            validate_platform_url("http://127.0.0.1:41737/").unwrap(),
            "http://127.0.0.1:41737"
        );
        assert_eq!(
            validate_platform_url("https://link.example.com/").unwrap(),
            "https://link.example.com"
        );
    }

    #[test]
    fn platform_url_rejects_public_http() {
        assert!(validate_platform_url("http://link.example.com").is_err());
    }

    #[test]
    fn cleaning_redacts_common_secrets_and_home_path() {
        let result = clean_text(
            "token: abc123 password='hidden' api-key-example /Users/test/project",
            Path::new("/Users/test"),
        );
        assert_eq!(result, "token: *** password='***' api-key-example ~/project");
    }

    #[test]
    fn skill_references_are_deduplicated() {
        let result = extract_skill_refs(
            "/Users/test/.codex/skills/research/SKILL.md /tmp/skills/research/SKILL.md",
        );
        assert_eq!(result.len(), 1);
        assert!(result.contains("research"));
    }
}

#[tauri::command]
fn get_recent_logs(app: AppHandle) -> Result<Vec<String>, String> {
    let path = log_path(&app)?;
    if !path.exists() {
        return Ok(Vec::new());
    }
    let text = fs::read_to_string(path).map_err(|error| error.to_string())?;
    Ok(text.lines().rev().take(80).map(str::to_string).collect())
}

#[tauri::command]
fn unpair_agent(app: AppHandle) -> Result<AgentStateView, String> {
    let _ = credential("device-token")
        .and_then(|entry| entry.delete_credential().map_err(|error| error.to_string()));
    let _ = credential("device-signing-key")
        .and_then(|entry| entry.delete_credential().map_err(|error| error.to_string()));
    let path = config_path(&app)?;
    if path.exists() {
        fs::remove_file(path).map_err(|error| error.to_string())?;
    }
    append_log(&app, "unpaired", json!({}));
    state_view(&app, "unpaired")
}

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn create_tray(app: &tauri::App) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "打开 LinkAgent", true, None::<&str>)?;
    let sync = MenuItem::with_id(app, "sync", "立即同步 Codex", true, None::<&str>)?;
    let platform = MenuItem::with_id(app, "platform", "打开 Link 平台", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出 LinkAgent", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &sync, &platform, &quit])?;
    let mut builder = TrayIconBuilder::new()
        .menu(&menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => show_main_window(app),
            "sync" => {
                let handle = app.clone();
                tauri::async_runtime::spawn(async move {
                    let _ = run_sync_guarded(&handle).await;
                });
            }
            "platform" => {
                if let Ok(Some(config)) = read_config(app) {
                    let _ = app.opener().open_url(config.platform_url, None::<&str>);
                }
            }
            "quit" => app.exit(0),
            _ => {}
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(RuntimeState::default())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            None,
        ))
        .setup(|app| {
            ensure_dirs(app.handle()).map_err(std::io::Error::other)?;
            create_tray(app)?;
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                loop {
                    if read_config(&handle).is_ok_and(|config| config.is_some()) {
                        if let Err(error) = heartbeat_once(&handle).await {
                            append_log(&handle, "heartbeat_failed", json!({ "error": error }));
                        }
                    }
                    tokio::time::sleep(Duration::from_secs(30)).await;
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_agent_state,
            pair_agent,
            authorize_codex,
            heartbeat,
            sync_codex,
            get_recent_logs,
            unpair_agent
        ])
        .build(tauri::generate_context!())
        .expect("error while building LinkAgent")
        .run(|_, event| if let RunEvent::ExitRequested { .. } = event {});
}
