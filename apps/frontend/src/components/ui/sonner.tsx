"use client";

import { Toaster as Sonner, ToasterProps } from "sonner";

/**
 * App-standardized toast surface.
 *
 * - No `richColors`: that's what produced the off-palette black/green toasts.
 *   Colors are mapped to the app's own CSS tokens (popover/border/...) so toasts
 *   match the rest of the UI, with subtle semantic tints for success/error/etc.
 * - Top-right placement, brief auto-dismiss, dismissible.
 */
const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="light"
      className="toaster group"
      position="top-right"
      closeButton
      duration={3500}
      visibleToasts={4}
      toastOptions={{
        classNames: {
          toast:
            "group toast rounded-lg border bg-popover text-popover-foreground shadow-lg",
          description: "text-muted-foreground",
          actionButton: "bg-primary text-primary-foreground",
          cancelButton: "bg-muted text-muted-foreground",
          success: "border-emerald-200 [&_[data-icon]]:text-emerald-600",
          error: "border-destructive/30 [&_[data-icon]]:text-destructive",
          warning: "border-amber-200 [&_[data-icon]]:text-amber-600",
          info: "border-sky-200 [&_[data-icon]]:text-sky-600",
        },
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
        } as React.CSSProperties
      }
      {...props}
    />
  );
};

export { Toaster };
