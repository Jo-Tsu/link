import { Component, type ErrorInfo, type ReactNode } from "react";
import { Icon } from "./Icon";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Smallink interface crashed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const chinese = (navigator.language || "").toLowerCase().startsWith("zh");
    return (
      <main className="min-h-screen bg-paper flex items-center justify-center px-6">
        <section className="w-full max-w-[460px] rounded-2xl border border-line bg-panel p-6 shadow-lg">
          <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-accentSoft text-accent">
            <Icon name="logo" size={22} />
          </div>
          <h1 className="text-[20px] font-semibold text-heading">
            {chinese ? "界面暂时无法显示" : "The interface could not be displayed"}
          </h1>
          <p className="mt-2 text-[13px] leading-relaxed text-muted">
            {chinese
              ? "Smallink 已保留本地数据。重新加载后仍有问题时，可在运行中心查看错误。"
              : "Your local data is safe. Reload Smallink, then check Runs if the problem continues."}
          </p>
          <details className="mt-4 rounded-lg border border-line bg-paper px-3 py-2 text-[11px] text-muted">
            <summary className="cursor-pointer">{chinese ? "错误详情" : "Error details"}</summary>
            <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words font-mono">
              {this.state.error.message}
            </pre>
          </details>
          <button
            className="mt-5 inline-flex h-9 items-center justify-center rounded-lg bg-accent px-4 text-[13px] font-medium text-white"
            onClick={() => window.location.reload()}
          >
            {chinese ? "重新加载" : "Reload"}
          </button>
        </section>
      </main>
    );
  }
}
