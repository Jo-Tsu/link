import { Link, useRouterState } from "@tanstack/react-router";
import { Bug, DatabaseZap, Settings2 } from "lucide-react";
import smallinkLogo from "@/assets/smallink-logo.webp";

const nav = [
  { title: "基础数据", url: "/", icon: DatabaseZap },
  { title: "平台采集", url: "/crawler", icon: Bug },
  { title: "设置", url: "/settings", icon: Settings2 },
];

export function TopNav() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const isActive = (url: string) => pathname === url || pathname.startsWith(`${url}/`);

  return (
    <header className="sticky top-0 z-20 border-b border-border/60 bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:gap-8 sm:px-6">
        <Link to="/" className="flex shrink-0 items-center gap-2.5">
          <div className="flex flex-col leading-tight">
            <img
              src={smallinkLogo}
              alt="Smallink"
              className="h-8 w-[136px] object-contain object-left"
            />
            <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              基础数据
            </span>
          </div>
        </Link>
        <nav className="flex min-w-0 items-center gap-1 overflow-x-auto">
          {nav.map((item) => (
            <Link
              key={item.url}
              to={item.url}
              className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-sm transition-colors ${
                isActive(item.url)
                  ? "bg-primary/12 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              }`}
            >
              <item.icon className="h-4 w-4" />
              <span>{item.title}</span>
            </Link>
          ))}
        </nav>
        <div className="ml-auto hidden text-xs text-muted-foreground md:block">原始数据平台</div>
      </div>
    </header>
  );
}
