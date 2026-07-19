import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AlertCircle,
  ChevronRight,
  DatabaseZap,
  FileJson,
  FolderOpen,
  RefreshCw,
  Search,
  Terminal,
} from "lucide-react";

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "基础数据 · link" }] }),
  component: DataIntakePage,
});

type Connector = {
  source: string;
  connectorName: string;
  containerCount: number;
  total: number;
  errors: number;
  latestSyncedAt: string;
  latestOccurredAt: string;
  rawTypes: Array<{ type: string; count: number }>;
};

type Origin = {
  source: string;
  originKey: string;
  sourceContainerId: string;
  sourceThreadId: string;
  sourceTitle: string;
  projectPath: string;
  sourceUri: string;
  recordCount: number;
  latestOccurredAt: string;
  rawTypes: Array<{ type: string; count: number }>;
};

const originPageSize = 10;

function DataIntakePage() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [origins, setOrigins] = useState<Origin[]>([]);
  const [selectedSource, setSelectedSource] = useState("");
  const [originTotal, setOriginTotal] = useState(0);
  const [originOffset, setOriginOffset] = useState(0);
  const [searchDraft, setSearchDraft] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingOrigins, setLoadingOrigins] = useState(false);
  const [error, setError] = useState("");

  const loadConnectors = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/connectors/status");
      const result = (await response.json()) as {
        connectors?: Connector[];
        error?: string;
      };
      if (!response.ok) throw new Error(result.error || "数据来源读取失败");
      const nextConnectors = result.connectors ?? [];
      setConnectors(nextConnectors);
      setSelectedSource((current) =>
        nextConnectors.some((connector) => connector.source === current) ? current : "",
      );
      setError("");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "数据来源读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadOrigins = useCallback(async (source: string, offset: number, query: string) => {
    if (!source) {
      setOrigins([]);
      setOriginTotal(0);
      return;
    }
    setLoadingOrigins(true);
    try {
      const params = new URLSearchParams({
        source,
        limit: String(originPageSize),
        offset: String(offset),
      });
      if (query) params.set("q", query);
      const response = await fetch(`/api/data-sources/origins?${params}`);
      const result = (await response.json()) as {
        origins?: Origin[];
        total?: number;
        error?: string;
      };
      if (!response.ok) throw new Error(result.error || "来源容器读取失败");
      setOrigins(result.origins ?? []);
      setOriginTotal(result.total ?? 0);
      setError("");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "来源容器读取失败");
    } finally {
      setLoadingOrigins(false);
    }
  }, []);

  useEffect(() => {
    void loadConnectors();
  }, [loadConnectors]);

  useEffect(() => {
    void loadOrigins(selectedSource, originOffset, appliedQuery);
  }, [appliedQuery, loadOrigins, originOffset, selectedSource]);

  const totalRecords = useMemo(
    () => connectors.reduce((total, connector) => total + connector.total, 0),
    [connectors],
  );
  const totalContainers = useMemo(
    () => connectors.reduce((total, connector) => total + connector.containerCount, 0),
    [connectors],
  );
  const errorCount = useMemo(
    () => connectors.reduce((total, connector) => total + connector.errors, 0),
    [connectors],
  );
  const selectedConnector = connectors.find((connector) => connector.source === selectedSource);

  function selectSource(source: string) {
    setSelectedSource((current) => (current === source ? "" : source));
    setOriginOffset(0);
    setSearchDraft("");
    setAppliedQuery("");
  }

  function refresh() {
    void loadConnectors();
    void loadOrigins(selectedSource, originOffset, appliedQuery);
  }

  function searchOrigins() {
    const nextQuery = searchDraft.trim();
    setOriginOffset(0);
    if (nextQuery === appliedQuery) void loadOrigins(selectedSource, 0, nextQuery);
    else setAppliedQuery(nextQuery);
  }

  return (
    <div className="space-y-7 p-4 sm:p-6">
      <section className="flex flex-wrap items-end justify-between gap-4 border-b border-border/60 pb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">基础数据</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            查看所有连接器同步进来的原始信息，并追溯到具体会话、文档或文件。
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh} disabled={loading || loadingOrigins}>
          <RefreshCw className={`h-4 w-4 ${loading || loadingOrigins ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </section>

      {error && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4" />
          {error}
        </div>
      )}

      <section className="grid gap-3 sm:grid-cols-3">
        <Metric label="数据来源" value={connectors.length} hint="已同步数据的连接器" />
        <Metric label="来源容器" value={totalContainers} hint="会话、文档与文件" />
        <Metric label="原始记录" value={totalRecords} hint="未经加工的原始内容" />
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">数据来源</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              选择一个连接器，查看它同步进来的内容。
            </p>
          </div>
          {errorCount > 0 && <Badge variant="outline">{errorCount} 条同步异常</Badge>}
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {connectors.map((connector) => {
            const active = connector.source === selectedSource;
            return (
              <button
                key={connector.source}
                type="button"
                aria-pressed={active}
                aria-expanded={active}
                onClick={() => selectSource(connector.source)}
                className={`min-h-36 rounded-md border p-4 text-left transition-colors ${
                  active
                    ? "border-primary bg-primary/5"
                    : "border-border/60 bg-card hover:border-primary/50 hover:bg-accent/25"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <Terminal className="h-4 w-4 shrink-0 text-primary" />
                    <span className="truncate font-medium">{connector.connectorName}</span>
                  </div>
                  <Badge variant={connector.total ? "secondary" : "outline"}>
                    {connector.total ? "已同步" : "暂无数据"}
                  </Badge>
                </div>
                <div className="mt-5 flex gap-8">
                  <SourceStat label="容器" value={connector.containerCount} />
                  <SourceStat label="记录" value={connector.total} />
                </div>
                <div className="mt-4 flex items-center justify-between gap-3 text-xs text-muted-foreground">
                  <span>
                    最近更新 {formatDate(connector.latestOccurredAt || connector.latestSyncedAt)}
                  </span>
                  <ChevronRight
                    className={`h-4 w-4 shrink-0 transition-transform ${active ? "rotate-90" : ""}`}
                  />
                </div>
              </button>
            );
          })}
          {!loading && connectors.length === 0 && <EmptyState />}
        </div>
      </section>

      {selectedConnector && (
        <section className="space-y-4 border-t border-border/60 pt-6">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <FolderOpen className="h-5 w-5 text-primary" />
                <h2 className="text-lg font-semibold">{selectedConnector.connectorName}</h2>
                <Badge variant="outline">{originTotal.toLocaleString()} 个容器</Badge>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                选择一个容器，查看其中保存的原始记录。
              </p>
            </div>
            <Button variant="outline" size="sm" asChild>
              <a href={`/data?source=${encodeURIComponent(selectedSource)}`}>
                <FileJson className="h-4 w-4" />
                全部原始记录
              </a>
            </Button>
          </div>

          <div className="flex max-w-2xl gap-2">
            <Input
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && searchOrigins()}
              placeholder="搜索名称、项目或来源路径"
            />
            <Button variant="outline" onClick={searchOrigins} disabled={loadingOrigins}>
              <Search className="h-4 w-4" />
              搜索
            </Button>
            {appliedQuery && (
              <Button
                variant="ghost"
                onClick={() => {
                  setSearchDraft("");
                  setAppliedQuery("");
                  setOriginOffset(0);
                }}
              >
                清除
              </Button>
            )}
          </div>

          <div className="overflow-hidden rounded-md border border-border/60 bg-card">
            {origins.map((origin, index) => {
              const containerId =
                origin.sourceContainerId || origin.sourceThreadId || origin.originKey;
              return (
                <a
                  key={`${origin.source}-${origin.originKey}`}
                  href={`/data?source=${encodeURIComponent(origin.source)}&container=${encodeURIComponent(containerId)}`}
                  className={`grid gap-3 p-4 transition-colors hover:bg-accent/30 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-center ${index ? "border-t border-border/60" : ""}`}
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">
                      {origin.sourceTitle || "未命名来源"}
                    </div>
                    <div
                      className="mt-1 truncate text-xs text-muted-foreground"
                      title={origin.projectPath || origin.sourceUri}
                    >
                      {sourceLocationLabel(origin.projectPath, origin.sourceUri)}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5 md:justify-end">
                    {origin.rawTypes.slice(0, 2).map((item) => (
                      <Badge key={item.type} variant="outline">
                        {rawTypeLabel(item.type)} {item.count}
                      </Badge>
                    ))}
                    {origin.rawTypes.length > 2 && (
                      <Badge variant="outline">+{origin.rawTypes.length - 2} 类</Badge>
                    )}
                  </div>
                  <div className="flex min-w-32 items-center justify-between gap-3 md:justify-end">
                    <div className="text-right">
                      <div className="text-sm font-medium">
                        {origin.recordCount.toLocaleString()} 条
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {formatDate(origin.latestOccurredAt)}
                      </div>
                    </div>
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                  </div>
                </a>
              );
            })}
            {loadingOrigins && (
              <div className="p-6 text-center text-sm text-muted-foreground">正在读取来源容器</div>
            )}
          </div>

          {!loadingOrigins && origins.length === 0 && (
            <EmptyState
              message={appliedQuery ? "没有匹配的来源容器。" : "这个来源暂时没有同步到容器。"}
            />
          )}

          {originTotal > originPageSize && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-sm text-muted-foreground">
                {originOffset + 1}-{Math.min(originOffset + origins.length, originTotal)} /{" "}
                {originTotal}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={originOffset === 0 || loadingOrigins}
                  onClick={() =>
                    setOriginOffset((current) => Math.max(0, current - originPageSize))
                  }
                >
                  上一页
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={originOffset + originPageSize >= originTotal || loadingOrigins}
                  onClick={() => setOriginOffset((current) => current + originPageSize)}
                >
                  下一页
                </Button>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: number; hint: string }) {
  return (
    <div className="border-l-2 border-primary/40 px-4 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value.toLocaleString()}</div>
      <div className="mt-1 text-xs text-muted-foreground">{hint}</div>
    </div>
  );
}

function SourceStat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value.toLocaleString()}</div>
    </div>
  );
}

function EmptyState({ message = "暂无接入数据。" }: { message?: string }) {
  return (
    <div className="rounded-md border border-dashed border-border/60 p-8 text-center text-sm text-muted-foreground">
      <DatabaseZap className="mx-auto h-6 w-6" />
      <div className="mt-2">{message}</div>
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

function rawTypeLabel(type: string) {
  return (
    { user_input: "用户输入", codex_output: "Codex 输出", cli: "CLI", tool: "工具", skill: "技能" }[
      type
    ] || type
  );
}
