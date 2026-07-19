import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Globe2,
  LoaderCircle,
  Sparkles,
  Bug,
  Download,
  FileCode2,
  FileText,
  Plus,
} from "lucide-react";

export const Route = createFileRoute("/crawler")({
  head: () => ({ meta: [{ title: "网页采集 · link" }] }),
  component: CrawlerPage,
});

type Mode = "static" | "dynamic" | "stealth";
type RuleField = {
  name: string;
  selector: string;
  selector_type: "css" | "xpath";
  multiple: boolean;
};
type CrawlOptions = {
  timeout_ms: number;
  wait_ms: number;
  wait_selector: string;
  network_idle: boolean;
  disable_resources: boolean;
  block_ads: boolean;
  adaptive: boolean;
  huge_tree: boolean;
};
type Job = {
  id: string;
  url: string;
  mode: Mode;
  status: "queued" | "running" | "succeeded" | "failed";
  created_at: number;
  error?: string | null;
  result?: {
    title: string;
    status_code: number;
    text: string;
    html: string;
    fields?: Record<string, string | string[] | null>;
    truncated: boolean;
  } | null;
};
const api = "http://127.0.0.1:18744/api";
const modeLabel: Record<Mode, string> = {
  static: "静态 HTTP",
  dynamic: "动态浏览器",
  stealth: "隐身浏览器",
};
const defaultOptions: CrawlOptions = {
  timeout_ms: 30000,
  wait_ms: 0,
  wait_selector: "",
  network_idle: true,
  disable_resources: false,
  block_ads: true,
  adaptive: false,
  huge_tree: false,
};

function CrawlerPage() {
  const [section, setSection] = useState<"overview" | "tasks" | "rules" | "results" | "settings">(
    "overview",
  );
  const [jobs, setJobs] = useState<Job[]>([]);
  const [active, setActive] = useState<Job | null>(null);
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<Mode>("static");
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState<"text" | "html">("text");
  const [notice, setNotice] = useState("Scrapling 引擎已连接。仅可采集公开互联网内容。");
  const [ruleName, setRuleName] = useState("默认采集规则");
  const [fields, setFields] = useState<RuleField[]>([
    { name: "页面标题", selector: "title::text", selector_type: "css", multiple: false },
  ]);
  const [options, setOptions] = useState<CrawlOptions>(defaultOptions);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem("link:crawler-rule");
      if (!saved) return;
      const parsed = JSON.parse(saved) as {
        name?: string;
        fields?: RuleField[];
        options?: Partial<CrawlOptions>;
      };
      if (parsed.name) setRuleName(parsed.name);
      if (parsed.fields?.length) setFields(parsed.fields);
      if (parsed.options) setOptions({ ...defaultOptions, ...parsed.options });
    } catch {
      setNotice("已使用默认采集配置，本地保存的规则无法读取。");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadJobs() {
      try {
        const response = await fetch(`${api}/crawls`);
        const payload = (await response.json()) as { jobs?: Job[]; detail?: string };
        if (!response.ok) throw new Error(payload.detail || "读取任务失败");
        if (cancelled) return;
        const loaded = payload.jobs ?? [];
        setJobs(loaded);
        setActive((current) => current ?? loaded[0] ?? null);
        setNotice(
          loaded.length
            ? `Scrapling 引擎已连接，已加载 ${loaded.length} 条任务记录。`
            : "Scrapling 引擎已连接。仅可采集公开互联网内容。",
        );
      } catch (error) {
        if (!cancelled)
          setNotice(`采集服务连接失败：${error instanceof Error ? error.message : "请稍后重试"}`);
      }
    }
    void loadJobs();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(async () => {
      const pending = jobs.filter((job) => job.status === "queued" || job.status === "running");
      if (!pending.length) return;
      const updates = await Promise.all(
        pending.map(async (job) => {
          const response = await fetch(`${api}/crawls/${job.id}`);
          return response.ok ? (response.json() as Promise<Job>) : job;
        }),
      );
      setJobs((current) => current.map((job) => updates.find((item) => item.id === job.id) ?? job));
      setActive((current) =>
        current ? (updates.find((item) => item.id === current.id) ?? current) : null,
      );
    }, 1000);
    return () => clearInterval(timer);
  }, [jobs]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setCreating(true);
    setNotice("正在创建采集任务…");
    try {
      const response = await fetch(`${api}/crawls`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          mode,
          ...options,
          wait_selector: options.wait_selector.trim() || null,
          fields: fields.filter((field) => field.name.trim() && field.selector.trim()),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "创建失败");
      const job: Job = {
        id: payload.id,
        url,
        mode,
        status: payload.status,
        created_at: Date.now() / 1000,
      };
      setJobs((current) => [job, ...current]);
      setActive(job);
      setOpen(false);
      setUrl("");
      setNotice("任务已创建，正在后台执行。");
    } catch (error) {
      setNotice(`创建失败：${error instanceof Error ? error.message : "请稍后重试"}`);
    } finally {
      setCreating(false);
    }
  }
  function download(kind: "text" | "html") {
    if (!active?.result) return;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(
      new Blob([active.result[kind]], { type: kind === "html" ? "text/html" : "text/plain" }),
    );
    link.download = `crawl-${active.id.slice(0, 8)}.${kind === "html" ? "html" : "txt"}`;
    link.click();
    URL.revokeObjectURL(link.href);
  }
  function saveRule() {
    window.localStorage.setItem(
      "link:crawler-rule",
      JSON.stringify({ name: ruleName, fields, options }),
    );
    const now = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    setSavedAt(now);
    setNotice(`采集规则“${ruleName}”已保存，并会自动应用到新任务。`);
  }
  const done = jobs.filter((job) => job.status === "succeeded").length;

  const completed = jobs.filter((job) => job.status === "succeeded");
  return (
    <div className="space-y-5 p-6">
      <section className="rounded-lg border border-border/60 bg-card p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <Badge variant="secondary" className="mb-3">
              <Bug className="h-3.5 w-3.5" /> Scrapling Engine
            </Badge>
            <h1 className="text-3xl font-semibold tracking-tight">网页采集</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              将公开网页转化为可阅读、可下载的内容。支持静态页面与 JavaScript
              页面采集，任务结果统一留痕。
            </p>
          </div>
          <CreateDialog
            open={open}
            setOpen={setOpen}
            url={url}
            setUrl={setUrl}
            mode={mode}
            setMode={setMode}
            creating={creating}
            create={create}
          />
        </div>
        <div className="mt-5 rounded-md border border-primary/15 bg-primary/5 px-3 py-2 text-xs text-muted-foreground">
          {notice}
        </div>
      </section>
      <nav className="flex gap-1 overflow-x-auto rounded-md border border-border/60 bg-card p-1">
        {[
          ["overview", "概览"],
          ["tasks", "任务"],
          ["rules", "采集规则"],
          ["results", "结果数据"],
          ["settings", "资源与策略"],
        ].map(([key, label]) => (
          <Button
            key={key}
            variant={section === key ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setSection(key as typeof section)}
          >
            {label}
          </Button>
        ))}
      </nav>
      {section === "overview" && (
        <>
          <section className="grid gap-3 sm:grid-cols-3">
            <Metric label="全部任务" value={jobs.length} hint="后端任务记录" />
            <Metric
              label="执行中"
              value={
                jobs.filter((job) => job.status === "queued" || job.status === "running").length
              }
              hint="实时更新"
            />
            <Metric
              label="已完成"
              value={done}
              hint={jobs.length ? `成功率 ${Math.round((done / jobs.length) * 100)}%` : "等待任务"}
            />
          </section>
          <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(340px,.85fr)]">
            <TaskPanel
              jobs={jobs.slice(0, 5)}
              open={open}
              setOpen={setOpen}
              url={url}
              setUrl={setUrl}
              mode={mode}
              setMode={setMode}
              creating={creating}
              create={create}
              setActive={setActive}
              setTab={setTab}
            />
            <ResultPanel active={active} tab={tab} setTab={setTab} download={download} />
          </section>
        </>
      )}
      {section === "tasks" && (
        <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(340px,.85fr)]">
          <TaskPanel
            jobs={jobs}
            open={open}
            setOpen={setOpen}
            url={url}
            setUrl={setUrl}
            mode={mode}
            setMode={setMode}
            creating={creating}
            create={create}
            setActive={setActive}
            setTab={setTab}
          />
          <ResultPanel active={active} tab={tab} setTab={setTab} download={download} />
        </section>
      )}
      {section === "rules" && (
        <RuleBuilder
          ruleName={ruleName}
          setRuleName={setRuleName}
          fields={fields}
          setFields={setFields}
          options={options}
          setOptions={setOptions}
          savedAt={savedAt}
          onSave={saveRule}
          onRun={() => setOpen(true)}
        />
      )}
      {section === "results" && (
        <Card className="border-border/60">
          <CardHeader>
            <CardTitle>结果数据</CardTitle>
          </CardHeader>
          <CardContent>
            {completed.length ? (
              <div className="divide-y divide-border/60">
                {completed.map((job) => (
                  <button
                    key={job.id}
                    className="flex w-full items-center justify-between py-3 text-left"
                    onClick={() => {
                      setActive(job);
                      setSection("tasks");
                    }}
                  >
                    <span className="min-w-0">
                      <b className="block truncate text-sm">{job.result?.title || job.url}</b>
                      <small className="block truncate text-xs text-muted-foreground">
                        {job.url}
                      </small>
                    </span>
                    <Badge variant="secondary">HTTP {job.result?.status_code}</Badge>
                  </button>
                ))}
              </div>
            ) : (
              <Empty onCreate={() => setOpen(true)} />
            )}
          </CardContent>
        </Card>
      )}
      {section === "settings" && (
        <section className="grid gap-4 md:grid-cols-3">
          <PolicyCard
            title="域名与 robots 策略"
            body="默认拒绝内网地址，并提示遵守目标网站条款与 robots.txt。"
          />
          <PolicyCard
            title="运行资源"
            body="静态请求与浏览器抓取通过 Scrapling 引擎执行；当前本地并发为 2。"
          />
          <PolicyCard
            title="任务与结果"
            body="任务结果在本地服务中保存，用于查看、复制和下载正文或 HTML。"
          />
        </section>
      )}
    </div>
  );
}

function TaskPanel({
  jobs,
  open,
  setOpen,
  url,
  setUrl,
  mode,
  setMode,
  creating,
  create,
  setActive,
  setTab,
}: {
  jobs: Job[];
  open: boolean;
  setOpen: (value: boolean) => void;
  url: string;
  setUrl: (value: string) => void;
  mode: Mode;
  setMode: (value: Mode) => void;
  creating: boolean;
  create: (event: React.FormEvent) => void;
  setActive: (job: Job) => void;
  setTab: (value: "text" | "html") => void;
}) {
  return (
    <Card className="border-border/60">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-base">
          <Globe2 className="h-4 w-4 text-primary" />
          采集任务
        </CardTitle>
        <CreateDialog
          open={open}
          setOpen={setOpen}
          url={url}
          setUrl={setUrl}
          mode={mode}
          setMode={setMode}
          creating={creating}
          create={create}
          compact
        />
      </CardHeader>
      <CardContent>
        {jobs.length ? (
          <div className="divide-y divide-border/60">
            {jobs.map((job) => (
              <button
                key={job.id}
                onClick={() => {
                  setActive(job);
                  setTab("text");
                }}
                className="flex w-full items-center gap-3 py-3 text-left transition hover:bg-accent/40"
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <Globe2 className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {job.result?.title || new URL(job.url).hostname}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">{job.url}</div>
                </div>
                <div className="text-right">
                  <Status status={job.status} />
                  <div className="mt-1 text-[10px] text-muted-foreground">
                    {modeLabel[job.mode]}
                  </div>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <Empty onCreate={() => setOpen(true)} />
        )}
      </CardContent>
    </Card>
  );
}
function ResultPanel({
  active,
  tab,
  setTab,
  download,
}: {
  active: Job | null;
  tab: "text" | "html";
  setTab: (value: "text" | "html") => void;
  download: (value: "text" | "html") => void;
}) {
  return (
    <Card className="border-border/60 bg-card/70">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4 text-primary" />
          {active ? "任务结果" : "开始采集"}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {active ? (
          <Result job={active} tab={tab} setTab={setTab} download={download} />
        ) : (
          <div className="py-7 text-center text-sm text-muted-foreground">
            选择一个任务查看内容，或创建新的采集任务。
          </div>
        )}
      </CardContent>
    </Card>
  );
}
function PolicyCard({ title, body }: { title: string; body: string }) {
  return (
    <Card className="border-border/60">
      <CardContent className="p-5">
        <h2 className="font-medium">{title}</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{body}</p>
      </CardContent>
    </Card>
  );
}

function RuleBuilder({
  ruleName,
  setRuleName,
  fields,
  setFields,
  options,
  setOptions,
  savedAt,
  onSave,
  onRun,
}: {
  ruleName: string;
  setRuleName: (value: string) => void;
  fields: RuleField[];
  setFields: React.Dispatch<React.SetStateAction<RuleField[]>>;
  options: CrawlOptions;
  setOptions: React.Dispatch<React.SetStateAction<CrawlOptions>>;
  savedAt: string | null;
  onSave: () => void;
  onRun: () => void;
}) {
  const update = (index: number, patch: Partial<RuleField>) =>
    setFields((current) =>
      current.map((field, fieldIndex) => (fieldIndex === index ? { ...field, ...patch } : field)),
    );
  const setOption = <K extends keyof CrawlOptions>(key: K, value: CrawlOptions[K]) =>
    setOptions((current) => ({ ...current, [key]: value }));
  return (
    <Card className="border-border/60">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileCode2 className="h-4 w-4 text-primary" />
          采集规则
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div>
          <label className="text-sm font-medium">规则名称</label>
          <Input
            className="mt-2 max-w-md"
            value={ruleName}
            onChange={(event) => setRuleName(event.target.value)}
            placeholder="例如：竞品商品信息"
          />
        </div>
        <div>
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium">需要采集的字段</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                定义字段名以及在页面中定位内容的 CSS 或 XPath 选择器。
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setFields((current) => [
                  ...current,
                  { name: "", selector: "", selector_type: "css", multiple: false },
                ])
              }
            >
              <Plus className="h-4 w-4" />
              添加字段
            </Button>
          </div>
          <div className="mt-3 space-y-3">
            {fields.map((field, index) => (
              <div
                key={index}
                className="grid gap-2 rounded-md border border-border/60 p-3 md:grid-cols-[1fr_110px_2fr_90px_auto]"
              >
                <Input
                  value={field.name}
                  onChange={(event) => update(index, { name: event.target.value })}
                  placeholder="字段名，如价格"
                />
                <select
                  className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                  value={field.selector_type}
                  onChange={(event) =>
                    update(index, { selector_type: event.target.value as "css" | "xpath" })
                  }
                >
                  <option value="css">CSS</option>
                  <option value="xpath">XPath</option>
                </select>
                <Input
                  value={field.selector}
                  onChange={(event) => update(index, { selector: event.target.value })}
                  placeholder={
                    field.selector_type === "css" ? ".price::text" : "//span[@class='price']/text()"
                  }
                />
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={field.multiple}
                    onChange={(event) => update(index, { multiple: event.target.checked })}
                  />
                  多值
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={fields.length === 1}
                  onClick={() =>
                    setFields((current) => current.filter((_, fieldIndex) => fieldIndex !== index))
                  }
                >
                  删除
                </Button>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-medium">执行配置</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            这些参数会随规则保存，并真实传给 Scrapling 抓取引擎。
          </p>
          <div className="mt-3 grid gap-3 rounded-md border border-border/60 p-4 md:grid-cols-2">
            <label className="text-xs font-medium">
              请求超时（秒）
              <Input
                className="mt-2"
                type="number"
                min="1"
                max="60"
                value={options.timeout_ms / 1000}
                onChange={(event) => setOption("timeout_ms", Number(event.target.value) * 1000)}
              />
            </label>
            <label className="text-xs font-medium">
              页面加载后等待（毫秒）
              <Input
                className="mt-2"
                type="number"
                min="0"
                max="10000"
                value={options.wait_ms}
                onChange={(event) => setOption("wait_ms", Number(event.target.value))}
              />
            </label>
            <label className="text-xs font-medium md:col-span-2">
              等待元素出现（CSS，可选）
              <Input
                className="mt-2"
                value={options.wait_selector}
                onChange={(event) => setOption("wait_selector", event.target.value)}
                placeholder="#product-detail 或 .price"
              />
            </label>
            <ConfigToggle
              label="等待网络空闲"
              checked={options.network_idle}
              onChange={(value) => setOption("network_idle", value)}
            />
            <ConfigToggle
              label="拦截广告与追踪请求"
              checked={options.block_ads}
              onChange={(value) => setOption("block_ads", value)}
            />
            <ConfigToggle
              label="禁用图片、字体等资源"
              checked={options.disable_resources}
              onChange={(value) => setOption("disable_resources", value)}
            />
            <ConfigToggle
              label="启用自适应元素定位"
              checked={options.adaptive}
              onChange={(value) => setOption("adaptive", value)}
            />
            <ConfigToggle
              label="允许解析超大 DOM"
              checked={options.huge_tree}
              onChange={(value) => setOption("huge_tree", value)}
            />
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground">
            {fields.filter((field) => field.name && field.selector).length} 个有效字段 · 超时{" "}
            {options.timeout_ms / 1000} 秒{savedAt ? ` · 最近保存 ${savedAt}` : " · 尚未保存"}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onSave}>
              保存配置
            </Button>
            <Button onClick={onRun}>使用此规则创建任务</Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ConfigToggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-md bg-muted/40 px-3 py-2 text-xs font-medium">
      <span>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
    </label>
  );
}

function CreateDialog(props: {
  open: boolean;
  setOpen: (value: boolean) => void;
  url: string;
  setUrl: (value: string) => void;
  mode: Mode;
  setMode: (value: Mode) => void;
  creating: boolean;
  create: (event: React.FormEvent) => void;
  compact?: boolean;
}) {
  const trigger = props.compact ? (
    <Button variant="outline" size="sm">
      <Plus className="h-4 w-4" />
      新建
    </Button>
  ) : (
    <Button onClick={() => props.setOpen(true)}>
      <Plus className="h-4 w-4" />
      新建采集任务
    </Button>
  );
  return (
    <Dialog open={props.open} onOpenChange={props.setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>创建采集任务</DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={props.create}>
          <div>
            <label className="text-sm font-medium">目标网址</label>
            <Input
              className="mt-2"
              placeholder="https://example.com"
              type="url"
              required
              value={props.url}
              onChange={(event) => props.setUrl(event.target.value)}
            />
          </div>
          <div>
            <label className="text-sm font-medium">抓取模式</label>
            <div className="mt-2 grid gap-2">
              {(["static", "dynamic", "stealth"] as Mode[]).map((item) => (
                <button
                  type="button"
                  onClick={() => props.setMode(item)}
                  className={`rounded-md border p-3 text-left text-sm ${props.mode === item ? "border-primary bg-primary/5" : "border-border"}`}
                  key={item}
                >
                  <b>{modeLabel[item]}</b>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {item === "static"
                      ? "普通网页，速度最快"
                      : item === "dynamic"
                        ? "等待 JavaScript 渲染"
                        : "仅限有授权的公开页面"}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <p className="text-xs leading-5 text-muted-foreground">
            平台会拒绝内网地址。请遵守目标网站条款、robots.txt 与适用法律。
          </p>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => props.setOpen(false)}>
              取消
            </Button>
            <Button disabled={props.creating}>{props.creating ? "创建中…" : "创建并运行"}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
function Status({ status }: { status: Job["status"] }) {
  return (
    <Badge
      variant={
        status === "succeeded" ? "secondary" : status === "failed" ? "destructive" : "outline"
      }
    >
      {status === "queued"
        ? "排队中"
        : status === "running"
          ? "执行中"
          : status === "succeeded"
            ? "已完成"
            : "失败"}
    </Badge>
  );
}
function Result({
  job,
  tab,
  setTab,
  download,
}: {
  job: Job;
  tab: "text" | "html";
  setTab: (value: "text" | "html") => void;
  download: (value: "text" | "html") => void;
}) {
  if (job.status === "queued" || job.status === "running")
    return (
      <div className="flex items-center gap-3 py-7 text-sm text-muted-foreground">
        <LoaderCircle className="h-5 w-5 animate-spin text-primary" />
        正在抓取网页，结果会自动更新。
      </div>
    );
  if (job.status === "failed")
    return (
      <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
        {job.error || "任务执行失败"}
      </div>
    );
  if (!job.result) return null;
  const extracted = job.result.fields && Object.keys(job.result.fields).length > 0;
  return (
    <div className="space-y-3">
      {extracted && (
        <div className="rounded-md border border-primary/20 bg-primary/5 p-3">
          <div className="mb-2 text-xs font-medium text-primary">结构化字段</div>
          <dl className="grid gap-2">
            {Object.entries(job.result.fields!).map(([name, value]) => (
              <div className="grid grid-cols-[110px_1fr] gap-2 text-xs" key={name}>
                <dt className="text-muted-foreground">{name}</dt>
                <dd className="break-words font-medium">
                  {Array.isArray(value) ? value.join("、") : (value ?? "未命中")}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-1">
          <Button
            variant={tab === "text" ? "default" : "outline"}
            size="sm"
            onClick={() => setTab("text")}
          >
            <FileText className="h-3.5 w-3.5" />
            正文
          </Button>
          <Button
            variant={tab === "html" ? "default" : "outline"}
            size="sm"
            onClick={() => setTab("html")}
          >
            <FileCode2 className="h-3.5 w-3.5" />
            HTML
          </Button>
        </div>
        <Button variant="outline" size="sm" onClick={() => download(tab)}>
          <Download className="h-3.5 w-3.5" />
          下载
        </Button>
      </div>
      <div className="text-xs text-muted-foreground">
        HTTP {job.result.status_code}
        {job.result.truncated ? " · 内容已截断" : ""}
      </div>
      <pre className="max-h-[430px] overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/50 p-3 text-xs leading-6">
        {job.result[tab]}
      </pre>
    </div>
  );
}
function Empty({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="py-12 text-center">
      <Bug className="mx-auto h-8 w-8 text-primary/60" />
      <h2 className="mt-3 text-sm font-medium">开始第一项网页采集</h2>
      <p className="mx-auto mt-2 max-w-sm text-xs leading-5 text-muted-foreground">
        输入一个公开网页地址，即可使用 Scrapling 抓取正文与原始 HTML。
      </p>
      <Button className="mt-4" size="sm" onClick={onCreate}>
        创建任务
      </Button>
    </div>
  );
}
function Metric({ label, value, hint }: { label: string; value: number; hint: string }) {
  return (
    <Card className="border-border/60">
      <CardContent className="p-4">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="mt-2 text-3xl font-semibold">{value}</div>
        <div className="mt-1 text-[11px] text-muted-foreground">{hint}</div>
      </CardContent>
    </Card>
  );
}
