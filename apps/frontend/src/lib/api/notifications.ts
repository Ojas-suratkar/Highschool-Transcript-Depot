import { apiFetch } from '@/lib/utils';

export type AppNotification = {
  id: number;
  created_at: string;
  level: 'info' | 'success' | 'warning' | 'error' | 'progress';
  category: string;
  title: string;
  message: string | null;
  read: boolean;
  meta: Record<string, unknown> | null;
};

export async function fetchNotifications(
  limit = 60,
): Promise<{ notifications: AppNotification[]; unread: number }> {
  return apiFetch(`/api/notifications?limit=${limit}`);
}

export async function markNotificationsRead(ids: number[]): Promise<void> {
  if (!ids.length) return;
  await apiFetch('/api/notifications/mark-read', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  });
}

export async function markAllNotificationsRead(): Promise<void> {
  await apiFetch('/api/notifications/mark-all-read', { method: 'POST' });
}

export async function clearReadNotifications(): Promise<void> {
  await apiFetch('/api/notifications/clear', { method: 'POST' });
}
