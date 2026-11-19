// Lightweight, app-wide notification bus. Any action can record a notification
// in one line — `emitNotification({ kind, title, message })` — without importing
// the notifications context. NotificationsProvider listens and files it into the
// term-scoped activity log (added → read when opened → removed when closed).

export type NotifyKind = 'success' | 'error' | 'info' | 'warn';

export type NotifyPayload = {
  kind?: NotifyKind;
  title: string;
  /** Extra metadata line shown under the title (counts, file names, term, etc.). */
  message?: string;
  /** Overrides the current term for this notification (defaults to the active term). */
  term?: string;
};

export const APP_NOTIFY_EVENT = 'app-notify';

export function emitNotification(payload: NotifyPayload): void {
  try {
    window.dispatchEvent(new CustomEvent<NotifyPayload>(APP_NOTIFY_EVENT, { detail: payload }));
  } catch {
    /* non-browser / disabled — ignore */
  }
}

/** Fired when a term is deleted so listeners can purge that term's state (the
 *  term-scoped activity log especially — otherwise a deleted-then-recreated term
 *  of the same name inherits the old term's notifications). */
export const APP_TERM_DELETED_EVENT = 'app-term-deleted';

export type TermDeletedPayload = { termId: string; termName?: string };

export function emitTermDeleted(payload: TermDeletedPayload): void {
  try {
    window.dispatchEvent(new CustomEvent<TermDeletedPayload>(APP_TERM_DELETED_EVENT, { detail: payload }));
  } catch {
    /* non-browser / disabled — ignore */
  }
}
