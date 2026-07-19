import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArrowLeft, ChevronDown, FileJson, Search } from "lucide-react";

export const Route = createFileRoute("/data")({
  head: () => ({ meta: [{ title: "原始数据 · link" }] }),
  component: RawDataPage,
});

type Connector = {
  source: string;
  connectorName: string;
  total: number;
  rawTypes: Array<{ type: string; count: number }>;
};

type RawRecord = {
  id: string;
  rawType: string;
  rawLabel: string;
  summary: string;
  rawText: string;
  occurredAt: string;
  syncedAt: string;
  threadTitle: string;
  projectPath: string;
  sourceUri: string;
  sourceRecordId: string;
  sensitivityLevel: string;
};

const pageSize = 30;

function RawDataPage() {
  const initial =
    typeof window === "undefined"
      ? new URLSearchParams()
      : new URLSearchParams(window.location.search);
  const [source, setSource] = useState(initial.get("source") || "");
  const [containerId, setContainerId] = useState(initial.get("container") || "");
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [records, setRecords] = useState<RawRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [rawType, setRawType] = useState("all");
  const [searchDraft, setSearchDraft] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadConnectors = useCallback(async () => {
    try {
      const response = await fetch("/api/connectors/status");
      const result = (await response.json()) as { connectors?: Connector[]; error?: string };
      if (!response.ok) throw new Error(result.error || "数据来源读取失败");
      const nextConnectors = result.connectors ?? [];
      setConnectors(nextConnectors);
      setSource((current) => current || nextConnectors[0]?.source || "");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "数据来源读取失败");
    }
  }, []);

  const loadRecords = useCallback(
    async (
      nextOffset: number,
      nextQuery: string,
      nextType: string,
      nextSource: string,
      nextContainer: string,
    ) => {
      if (!nextSource) return;
      setLoading(true);
      try {
        const params = new URLSearchParams({
          source: nextSource,
          rawType: nextType,
          limit: String(pageSize),
          offset: String(nextOffset),
        });
        if (nextContainer) params.set("originKeys", nextContainer);
        if (nextQuery) params.set("q", nextQuery);
        const response = await fetch(`/api/sensory-records?${params}`);
        const result = (await response.json()) as {
          records?: RawRecord[];
          total?: number;
          error?: string;
        };
        if (!response.ok) throw new Error(result.error || "原始数据读取失败");
        setRecords(result.records ?? []);
        setTotal(result.total ?? 0);
        setError("");
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "原始数据读取失败");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void loadConnectors();
  }, [loadConnectors]);

  useEffect(() => {
    void loadRecords(offset, appliedQuery, rawType, source, containerId);
  }, [appliedQuery, containerId, loadRecords, offset, rawType, source]);

  const connector = connectors.find((item) => item.source === source);
  const containerTitle = useMemo(
    () => (containerId ? records[0]?.threadTitle || "当前容器" : ""),
    [containerId, records],
  );

  function applyFilters() {
    const nextQuery = searchDraft.trim();
    setOffset(0);
    if (nextQuery === appliedQuery) void loadRecords(0, nextQuery, rawType, source, containerId);
    else setAppliedQuery(nextQuery);
  }

  function selectSource(nextSource: string) {
    setSource(nextSource);
    setContainerId("");
    setRawType("all");
    setSearchDraft("");
    setAppliedQuery("");
    setOffset(0);
    window.history.replaceState(null, "", `/data?source=${encodeURIComponent(nextSource)}`);
  }

  function clearContainer() {
    setContainerId("");
    setOffset(0);
    window.history.replaceState(null, "", `/data?source=${encodeURIComponent(source)}`);
  }

  return (
    <div className="space-y-5 p-4 sm:p-6">
      <header className="border-b border-border/60 pb-5">
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2">
          <Link to="/">
            <ArrowLeft className="h-4 w-4" />
            基础数据
          </Link>
        </Button>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
              <FileJson className="h-5 w-5 text-primary" />
              {connector?.connectorName || "原始数据"}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {containerTitle
                ? `当前容器：${containerTitle}`
                : "浏览该来源同步保存的全部原始记录。"}
            </p>
          </div>
          <Badge variant="outline">{total.toLocaleString()} 条记录</Badge>
        </div>
      </header>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <section className="space-y-3">
        {connectors.length > 1 && (
          <div className="flex flex-wrap gap-2">
            {connectors.map((item) => (
              <Button
                key={item.source}
                size="sm"
                variant={source === item.source ? "default" : "outline"}
                onClick={() => selectSource(item.source)}
              >
                {item.connectorName}
              </Button>
            ))}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <select
            aria-label="原始数据类型"
            value={rawType}
            onChange={(event) => {
              setRawType(event.target.value);
              setOffset(0);
            }}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="all">全部类型</option>
            {(connector?.rawTypes ?? []).map((item) => (
              <option key={item.type} value={item.type}>
                {rawTypeLabel(item.type)}
              </option>
            ))}
          </select>
          <Input
            value={searchDraft}
            onChange={(event) => setSearchDraft(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && applyFilters()}
            placeholder="搜索标题、项目或原始内容"
            className="max-w-md"
          />
          <Button variant="outline" onClick={applyFilters} disabled={loading}>
            <Search className="h-4 w-4" />
            搜索
          </Button>
          {appliedQuery && (
            <Button
              variant="ghost"
              onClick={() => {
                setSearchDraft("");
                setAppliedQuery("");
                setOffset(0);
              }}
            >
              清除搜索
            </Button>
          )}
          {containerId && (
            <Button variant="outline" onClick={clearContainer}>
              查看全部容器
            </Button>
          )}
        </div>
      </section>

      <section className="overflow-hidden rounded-md border border-border/60 bg-card">
        {records.map((record, index) => (
          <article key={record.id} className={`p-4 ${index ? "border-t border-border/60" : ""}`}>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{rawTypeLabel(record.rawType)}</Badge>
              {record.sensitivityLevel === "sensitive" && <Badge variant="outline">敏感内容</Badge>}
              <span className="text-xs text-muted-foreground">{formatDate(record.occurredAt)}</span>
            </div>
            <div className="mt-2 text-sm font-medium">{record.threadTitle || "未命名来源"}</div>
            <p className="mt-1 line-clamp-2 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
              {record.summary || record.rawText}
            </p>
            <div
              className="mt-2 text-xs text-muted-foreground"
              title={record.projectPath || record.sourceUri}
            >
              {sourceLocationLabel(record.projectPath, record.sourceUri)}
            </div>
            <details className="mt-3 text-sm">
              <summary className="inline-flex cursor-pointer items-center gap-1 text-primary">
                <ChevronDown className="h-4 w-4" />
                查看原文与来源
              </summary>
              <div className="mt-3 space-y-3 rounded-md bg-muted/50 p-3">
                <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words font-sans text-xs leading-5">
                  {record.rawText}
                </pre>
                <dl className="grid gap-2 border-t border-border/60 pt-3 text-xs text-muted-foreground sm:grid-cols-2">
                  <div>
                    <dt className="font-medium text-foreground">发生时间</dt>
                    <dd className="mt-0.5">{formatFullDate(record.occurredAt)}</dd>
                  </div>
                  <div>
                    <dt className="font-medium text-foreground">同步时间</dt>
                    <dd className="mt-0.5">{formatFullDate(record.syncedAt)}</dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="font-medium text-foreground">来源位置</dt>
                    <dd className="mt-0.5 break-all">
                      {record.projectPath || record.sourceUri || "未提供"}
                    </dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="font-medium text-foreground">来源记录 ID</dt>
                    <dd className="mt-0.5 break-all">{record.sourceRecordId || "未提供"}</dd>
                  </div>
                </dl>
              </div>
            </details>
          </article>
        ))}
        {loading && (
          <div className="p-8 text-center text-sm text-muted-foreground">正在读取原始数据</div>
        )}
      </section>

      {!loading && records.length === 0 && (
        <div className="rounded-md border border-dashed border-border/60 p-8 text-center text-sm text-muted-foreground">
          没有匹配的原始数据。
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <Button
          variant="outline"
          size="sm"
          disabled={offset === 0 || loading}
          onClick={() => setOffset((current) => Math.max(0, current - pageSize))}
        >
          上一页
        </Button>
        <span className="text-sm text-muted-foreground">
          {total ? `${offset + 1}-${Math.min(offset + records.length, total)} / ${total}` : "0 条"}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={offset + pageSize >= total || loading}
          onClick={() => setOffset((current) => current + pageSize)}
        >
          下一页
        </Button>
      </div>
    </div>
  );
}

function sourceLocationLabel(projectPath: string, sourceUri: string) {
  const value = projectPath || sourceUri;
  if (!value) return "未提供来源位置";
  const normalized = value.replace(/\\/g, "/").replace(/\/$/, "");
  const name = normalized.split("/").filter(Boolean).pop();
  return projectPath ? `项目：${name || projectPath}` : `来源：${name || sourceUri}`;
}

function formatDate(value: string) {
  if (!value) return "暂无";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatFullDate(value: string) {
  if (!value) return "暂无";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function rawTypeLabel(type: string) {
  return (
    { user_input: "用户输入", codex_output: "Codex 输出", cli: "CLI", tool: "工具", skill: "技能" }[
      type
    ] || type
  );
}
