import { useEffect, useRef } from "react";
import { setTurnstileToken } from "../api/client";

interface Props {
  siteKey?: string;
}

// Module-level guard so the Cloudflare script is injected only once
let _scriptInjected = false;

declare global {
  interface Window {
    turnstile?: {
      render: (
        container: HTMLElement,
        opts: {
          sitekey: string;
          callback?: (token: string) => void;
          "expired-callback"?: () => void;
          "error-callback"?: () => void;
          size?: "normal" | "compact" | "invisible";
          appearance?: "always" | "execute" | "interaction-only";
        },
      ) => string;
      reset: (widgetId?: string) => void;
      execute: (widgetId?: string) => void;
    };
  }
}

/**
 * Invisible Cloudflare Turnstile widget.
 *
 * Renders a 0×0 div, loads the CF script, validates on mount, and pushes the
 * resulting token into api/client via setTurnstileToken so subsequent POSTs
 * carry the `cf-turnstile-response` header.
 *
 * When `siteKey` is missing (local dev, dev preview), the widget no-ops and
 * the backend's TURNSTILE_ENABLED guard lets requests through.
 */
export function TurnstileWidget({ siteKey }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!siteKey) return;
    if (!containerRef.current) return;

    function loadScript(): Promise<void> {
      return new Promise((resolve) => {
        if (_scriptInjected) {
          // Already injected by a previous mount; resolve when global appears.
          const tick = () => (window.turnstile ? resolve() : setTimeout(tick, 50));
          tick();
          return;
        }
        _scriptInjected = true;
        const s = document.createElement("script");
        s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
        s.async = true;
        s.defer = true;
        s.onload = () => resolve();
        document.head.appendChild(s);
      });
    }

    let cancelled = false;
    loadScript().then(() => {
      if (cancelled || !containerRef.current || !window.turnstile || !siteKey) return;
      widgetIdRef.current = window.turnstile.render(containerRef.current, {
        sitekey: siteKey,
        size: "invisible",
        appearance: "execute",
        callback: (token) => setTurnstileToken(token),
        "expired-callback": () => {
          setTurnstileToken("");
          // Re-execute to get a fresh token
          if (widgetIdRef.current && window.turnstile) {
            window.turnstile.reset(widgetIdRef.current);
          }
        },
        "error-callback": () => setTurnstileToken(""),
      });
    });

    return () => {
      cancelled = true;
    };
  }, [siteKey]);

  return <div ref={containerRef} aria-hidden="true" style={{ width: 0, height: 0 }} />;
}
