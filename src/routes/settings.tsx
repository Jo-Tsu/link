import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Bot,
  Cable,
  Cpu,
  Download,
  KeyRound,
  LoaderCircle,
  Play,
  Save,
  Settings2,
  MonitorSmartphone,
} from "lucide-react";

export const Route = createFileRoute("/settings")({
  head: () => ({ meta: [{ title: "设置 · link" }] }),
  component: SettingsPage,
});

type Config = {
  id: string;
  category: "connector" | "model" | "agent";
  name: string;
  description: string;
  enabled: boolean;
  status: string;
  config: Record<string, unknown>;
  updatedAt: string;
};

type DeviceAgent = {
  id: string;
  displayName: string;
  status: string;
  version: string;
  operatingSystem: string;
  lastSeenAt: string;
};

const groups = [
  {
    category: "agent" as const,
    title: "智能体",
    description: "LinkAgent 客户端与未来智能体角色。",
    icon: Bot,
  },
  {
    category: "connector" as const,
    title: "连接器",
    description: "授权、读取范围和同步方式。",
    icon: Cable,
  },
  {
    category: "model" as const,
    title: "模型",
    description: "为后续能力预先保存模型连接配置，当前不会调用。",
    icon: Cpu,
  },
];

function SettingsPage() {
  const [configs, setConfigs] = useState<Config[]>([]);
  const [deviceAgents, setDeviceAgents] = useState<DeviceAgent[]>([]);
  const [selected, setSelected] = useState<Config | undefined>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [pairingCode, setPairingCode] = useState("");
  const platformOrigin =
    typeof window === "undefined" ? "http://127.0.0.1:41737" : window.location.origin;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [response, agentResponse] = await Promise.all([
        fetch("/api/settings"),
        fetch("/api/agents"),
      ]);
      const result = (await response.json()) as { configs?: Config[]; error?: string };
      const agentResult = (await agentResponse.json()) as {
        agents?: DeviceAgent[];
        error?: string;
      };
      if (!response.ok) throw new Error(result.error || "读取设置失败");
      if (!agentResponse.ok) throw new Error(agentResult.error || "读取 Agent 状态失败");
      setConfigs(result.configs ?? []);
      setDeviceAgents(agentResult.agents ?? []);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "读取设置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const grouped = useMemo(
    () =>
      new Map(
        groups.map((group) => [
          group.category,
          configs.filter((item) => item.category === group.category),
        ]),
      ),
    [configs],
  );

  async function save(input: { enabled: boolean; config: Record<string, unknown> }) {
    if (!selected) return;
    setSaving(true);
    try {
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: selected.id,
          enabled: input.enabled,
          status: input.enabled ? "configured" : "not_enabled",
          config: input.config,
        }),
      });
      const result = (await response.json()) as { config?: Config; error?: string };
      if (!response.ok || !result.config) throw new Error(result.error || "保存失败");
      setConfigs((current) =>
        current.map((item) => (item.id === result.config?.id ? result.config : item)),
      );
      setSelected(result.config);
      setNotice("配置已保存。当前不会启动模型或智能体执行数据处理。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function createPairingCode() {
    try {
      const response = await fetch("/api/agents/pairing-codes", { method: "POST" });
      const result = (await response.json()) as { code?: string; error?: string };
      if (!response.ok || !result.code) throw new Error(result.error || "创建配对码失败");
      setPairingCode(result.code);
      setNotice("配对码已创建，有效期 10 分钟。请在 LinkAgent 客户端中完成设备连接。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "创建配对码失败");
    }
  }

  async function requestCodexSync(agentId: string) {
    try {
      const response = await fetch("/api/agents/commands", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agentId,
          type: "sync_connector",
          payload: { connectorId: "codex_local" },
        }),
      });
      const result = (await response.json()) as { commandId?: string; error?: string };
      if (!response.ok || !result.commandId) throw new Error(result.error || "创建同步指令失败");
      setNotice("Codex 同步指令已创建，Agent 会在下一次心跳时执行。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "创建同步指令失败");
    }
  }

  return (
    <div className="space-y-6 p-6">
      <section className="rounded-lg border border-border/60 bg-card p-5 shadow-sm">
        <Badge variant="secondary" className="mb-3">
          <Settings2 className="h-3.5 w-3.5" /> 配置中心
        </Badge>
        <h1 className="text-3xl font-semibold tracking-tight">设置</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
          在这里配置连接器、模型和智能体。基础数据链路只同步原始信息；模型和智能体均为预配置，不会自动运行。
        </p>
        {notice && (
          <div className="mt-4 rounded-md bg-muted/60 p-3 text-sm text-muted-foreground">
            {notice}
          </div>
        )}
      </section>

      {groups.map((group) => {
        const Icon = group.icon;
        const items = grouped.get(group.category) ?? [];
        return (
          <section key={group.category} className="space-y-3">
            <div className="flex items-center gap-2">
              <Icon className="h-5 w-5 text-primary" />
              <div>
                <h2 className="text-lg font-semibold">{group.title}</h2>
                <p className="mt-0.5 text-sm text-muted-foreground">{group.description}</p>
              </div>
            </div>
            {group.category === "agent" && (
              <LinkAgentDevices
                agents={deviceAgents}
                loading={loading}
                pairingCode={pairingCode}
                platformOrigin={platformOrigin}
                onCreatePairingCode={createPairingCode}
                onSyncCodex={requestCodexSync}
              />
            )}
            <div className="grid gap-3 lg:grid-cols-2">
              {loading && (
                <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  正在读取配置
                </div>
              )}
              {items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelected(item)}
                  className="text-left"
                >
                  <Card className="h-full border-border/60 transition-colors hover:border-primary/50 hover:bg-accent/30">
                    <CardHeader className="flex flex-row items-start justify-between gap-3">
                      <div>
                        <CardTitle className="text-base">{item.name}</CardTitle>
                        <p className="mt-2 text-xs leading-5 text-muted-foreground">
                          {item.description}
                        </p>
                      </div>
                      <Badge variant={item.enabled ? "secondary" : "outline"}>
                        {item.enabled ? "已启用" : "未启用"}
                      </Badge>
                    </CardHeader>
                    <CardContent className="flex justify-between gap-3 text-xs text-muted-foreground">
                      <span>{statusLabel(item.status)}</span>
                      <span>点击配置</span>
                    </CardContent>
                  </Card>
                </button>
              ))}
            </div>
          </section>
        );
      })}

      <ConfigDialog
        config={selected}
        saving={saving}
        onOpenChange={(open) => !open && setSelected(undefined)}
        onSave={save}
      />
    </div>
  );
}

function LinkAgentDevices({
  agents,
  loading,
  pairingCode,
  platformOrigin,
  onCreatePairingCode,
  onSyncCodex,
}: {
  agents: DeviceAgent[];
  loading: boolean;
  pairingCode: string;
  platformOrigin: string;
  onCreatePairingCode: () => void;
  onSyncCodex: (agentId: string) => void;
}) {
  return (
    <div className="space-y-3 border-t border-border/60 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <MonitorSmartphone className="h-4 w-4 text-primary" />
          <div>
            <div className="text-sm font-medium">LinkAgent 客户端</div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              安装在用户电脑上，负责运行连接器与上传原始数据。
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" asChild>
            <a href="https://github.com/Jo-Tsu/link/releases/download/v0.2.0-developer-preview/LinkAgent_0.2.0_aarch64.dmg">
              <Download className="h-4 w-4" />
              下载 macOS 客户端
            </a>
          </Button>
          <Button variant="outline" size="sm" onClick={onCreatePairingCode}>
            <KeyRound className="h-4 w-4" />
            配对新设备
          </Button>
        </div>
      </div>
      {pairingCode && (
        <Card className="border-primary/30">
          <CardContent className="space-y-3 p-4">
            <div>
              <div className="text-xs text-muted-foreground">平台地址</div>
              <code className="mt-1 block break-all rounded-md border border-border/60 px-3 py-2 text-xs">
                {platformOrigin}
              </code>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">一次性配对码</div>
              <code className="mt-1 block break-all rounded-md bg-muted px-3 py-2 text-base font-semibold">
                {pairingCode}
              </code>
            </div>
            <p className="text-xs leading-5 text-muted-foreground">
              打开 LinkAgent，在配对页输入以上信息。配对成功后，这台设备会自动出现在下方列表中。
            </p>
          </CardContent>
        </Card>
      )}
      <div className="grid gap-3 lg:grid-cols-2">
        {agents.map((agent) => (
          <Card key={agent.id} className="border-border/60">
            <CardHeader className="flex flex-row items-start justify-between gap-3">
              <CardTitle className="text-base">{agent.displayName}</CardTitle>
              <Badge variant={agent.status === "online" ? "secondary" : "outline"}>
                {agent.status === "online" ? "在线" : "离线"}
              </Badge>
            </CardHeader>
            <CardContent className="space-y-3">
              <Button size="sm" variant="outline" onClick={() => onSyncCodex(agent.id)}>
                <Play className="h-4 w-4" />
                同步 Codex
              </Button>
              <details className="text-xs text-muted-foreground">
                <summary className="cursor-pointer">技术信息</summary>
                <div className="mt-2">
                  {agent.operatingSystem || "未知系统"} · {agent.version || "未上报版本"} · 最近心跳{" "}
                  {formatDate(agent.lastSeenAt)}
                </div>
              </details>
            </CardContent>
          </Card>
        ))}
        {!loading && agents.length === 0 && (
          <div className="rounded-md border border-dashed border-border/60 p-5 text-sm text-muted-foreground">
            尚未配对 LinkAgent。先下载安装客户端，再创建配对码完成连接。
          </div>
        )}
      </div>
    </div>
  );
}

function ConfigDialog({
  config,
  saving,
  onOpenChange,
  onSave,
}: {
  config?: Config;
  saving: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (input: { enabled: boolean; config: Record<string, unknown> }) => void;
}) {
  const [enabled, setEnabled] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!config) return;
    setEnabled(config.enabled);
    setValues(
      Object.fromEntries(
        Object.entries(config.config).map(([key, value]) => [key, String(value ?? "")]),
      ),
    );
  }, [config]);
  const fields = config ? Object.keys(config.config) : [];
  const commonFields = config
    ? fields.filter((field) => isCommonField(config.category, field))
    : [];
  const advancedFields = config
    ? fields.filter((field) => !isCommonField(config.category, field))
    : [];
  return (
    <Dialog open={Boolean(config)} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{config?.name || "配置"}</DialogTitle>
          <DialogDescription>{config?.description}</DialogDescription>
        </DialogHeader>
        {config && (
          <div className="space-y-4 py-2">
            <div className="flex items-center justify-between rounded-md border border-border/60 p-3">
              <div>
                <div className="text-sm font-medium">启用配置</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  启用只保存可用状态，不会执行同步、模型调用或智能体任务。
                </div>
              </div>
              <Switch checked={enabled} onCheckedChange={setEnabled} />
            </div>
            {commonFields.map((field) => (
              <div key={field} className="space-y-2">
                <Label htmlFor={`${config.id}-${field}`}>{fieldLabel(field)}</Label>
                <Input
                  id={`${config.id}-${field}`}
                  value={values[field] || ""}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [field]: event.target.value }))
                  }
                />
              </div>
            ))}
            {advancedFields.length > 0 && (
              <details className="rounded-md border border-border/60 p-3">
                <summary className="cursor-pointer text-sm font-medium">高级设置</summary>
                <div className="mt-3 space-y-3">
                  {advancedFields.map((field) => (
                    <div key={field} className="space-y-2">
                      <Label htmlFor={`${config.id}-${field}`}>{fieldLabel(field)}</Label>
                      <Input
                        id={`${config.id}-${field}`}
                        value={values[field] || ""}
                        onChange={(event) =>
                          setValues((current) => ({ ...current, [field]: event.target.value }))
                        }
                      />
                    </div>
                  ))}
                </div>
              </details>
            )}
            <Button
              className="w-full"
              disabled={saving}
              onClick={() => onSave({ enabled, config: values })}
            >
              <Save className="h-4 w-4" />
              {saving ? "保存中" : "保存配置"}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function statusLabel(status: string) {
  return (
    { connected: "已连接", configured: "已配置", not_configured: "待配置", not_enabled: "未启用" }[
      status
    ] || status
  );
}

function fieldLabel(field: string) {
  return (
    {
      syncMode: "同步方式",
      scope: "读取范围",
      model: "模型名称",
      baseUrl: "服务地址",
    }[field] || field
  );
}

function isCommonField(category: Config["category"], field: string) {
  if (category === "connector") return field === "scope";
  if (category === "model") return field === "model" || field === "baseUrl";
  return false;
}

function formatDate(value: string) {
  if (!value) return "暂无";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
