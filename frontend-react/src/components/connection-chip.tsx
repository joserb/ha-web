import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { brokerLink, browserLink, houseLink, summarize } from "@/lib/link";
import type { ConnectionChain } from "@/types/sensors";

/**
 * One chip for the whole browser → backend → broker → pihomeblk-1 chain, with
 * the per-leg detail behind a dropdown. A single all-or-nothing light would
 * hide WHICH leg needs fixing; three permanent chips were noise.
 */
export function ConnectionChip({ chain }: { chain: ConnectionChain }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const summary = summarize(chain);
  const legs = [
    { key: "browser", ...browserLink(chain) },
    { key: "broker", ...brokerLink(chain) },
    { key: "house", ...houseLink(chain) },
  ];

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="true"
        title="Connection chain: browser → backend → broker → pihomeblk-1"
        className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring ${summary.chipClass}`}
      >
        <span className={`size-2 rounded-full ${summary.dotClass}`} />
        {summary.label}
        <ChevronDown className={`size-3 opacity-60 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div
          role="group"
          aria-label="Connection chain detail"
          className="absolute right-0 top-full z-20 mt-1.5 w-max min-w-56 rounded-lg border bg-card p-1.5 shadow-lg"
        >
          {legs.map((leg) => (
            <div key={leg.key} className="grid gap-0.5 rounded px-2 py-1.5">
              <span className="flex items-center gap-2 text-sm text-card-foreground">
                <span className={`size-2 shrink-0 rounded-full ${leg.dotClass}`} />
                {leg.label}
              </span>
              <span className="pl-4 text-xs text-muted-foreground">{leg.hint}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
