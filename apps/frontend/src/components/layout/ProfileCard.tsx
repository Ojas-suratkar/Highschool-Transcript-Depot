import { useMemo, useState, useEffect } from 'react';
import { LogOut, Mail, UserRound, GraduationCap, BadgeCheck, Clock3, Pencil } from 'lucide-react';
import { toast } from 'sonner';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';

type ProfileCardVariant = 'sidebar' | 'header';

export function ProfileCard({ variant = 'sidebar' }: { variant?: ProfileCardVariant }) {
  const { user, logout, updateProfile, lastIssuedAtMs } = useAuth();
  const [open, setOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draftFirst, setDraftFirst] = useState(user?.first_name || '');
  const [draftLast, setDraftLast] = useState(user?.last_name || '');
  const [draftPhone, setDraftPhone] = useState(user?.phone || '');
  const [draftRole, setDraftRole] = useState(user?.role || '');

  const fullName = useMemo(() => {
    if (!user) return '';
    const first = user.first_name || '';
    const last = user.last_name || '';
    const full = `${first} ${last}`.trim();
    return full || user.email;
  }, [user]);

  const lastLoginDisplay = useMemo(() => {
    if (!lastIssuedAtMs) return '—';
    try {
      const dt = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/Los_Angeles',
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      }).format(new Date(lastIssuedAtMs));
      return dt + ' PT';
    } catch {
      return '—';
    }
  }, [lastIssuedAtMs]);

  if (!user) return null;

  useEffect(() => {
    if (open) {
      // reset drafts to latest user state whenever popover opens
      setDraftFirst(user.first_name || '');
      setDraftLast(user.last_name || '');
      setDraftPhone(user.phone || '');
      setDraftRole(user.role || '');
      setEditMode(false);
    }
  }, [open, user]);

  const saveDraft = async () => {
    setSaving(true);
    try {
      await updateProfile({
        first_name: draftFirst,
        last_name: draftLast,
        phone: draftPhone,
        role: draftRole,
      });
      setEditMode(false);
      toast.success('Profile updated');
    } catch {
      toast.error('Could not save your profile. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          aria-label="Profile"
          className={`flex items-center gap-2 border border-slate-200 bg-white shadow-[0_4px_14px_-10px_rgba(15,23,42,0.35)] hover:border-blue-200 transition ${
            variant === 'header'
              ? 'h-11 w-11 justify-center rounded-full p-0'
              : 'px-3 py-2 w-full rounded-lg'
          }`}
        >
          <Avatar className="h-10 w-10 bg-blue-50 text-blue-700 shrink-0 rounded-full border border-slate-200 shadow-[0_3px_10px_-8px_rgba(15,23,42,0.45)]">
            <AvatarFallback className="bg-blue-50 text-blue-700 font-semibold flex items-center justify-center rounded-full">
              <UserRound className="h-4 w-4" />
            </AvatarFallback>
          </Avatar>
          {variant === 'sidebar' && (
            <div className="min-w-0 text-left">
              <p className="truncate text-sm font-semibold text-slate-900">{fullName}</p>
              <p className="truncate text-[11px] text-slate-600 flex items-center gap-1">
                <Mail className="h-3 w-3" />
                {user.email}
              </p>
            </div>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align={variant === 'header' ? 'end' : 'start'}
        side="bottom"
        sideOffset={6}
        className={`${variant === 'header' ? 'w-80' : 'w-96'} p-4 space-y-3 shadow-lg`}
      >
        <div className="flex flex-col gap-3">
            <div className="grid grid-cols-[auto,1fr,auto] items-start gap-3">
              <div className="h-10 w-10 rounded-full bg-gradient-to-br from-blue-500 to-cyan-400 flex items-center justify-center text-white font-semibold">
                <UserRound className="h-5 w-5" />
              </div>
              <div className="leading-tight min-w-0">
                <p className="text-sm font-semibold text-slate-900 truncate">{fullName}</p>
                <p className="text-xs text-slate-600 flex items-center gap-1 truncate">
                  <Mail className="h-3.5 w-3.5" /> {user.email}
                </p>
                    {user.institution?.institution_name && (
                      <p className="mt-1 text-[11px] text-slate-700 truncate flex items-center gap-1">
                        <GraduationCap className="h-3.5 w-3.5 text-slate-600" />
                        {user.institution.institution_name}
                      </p>
                    )}
                {user.role && (
                  <p className="mt-1 text-[11px] text-slate-700 truncate flex items-center gap-1">
                    <BadgeCheck className="h-3.5 w-3.5 text-slate-600" />
                    {user.role}
                  </p>
                )}
                <p className="mt-1 text-[11px] text-slate-700 truncate flex items-center gap-1">
                  <Clock3 className="h-3.5 w-3.5 text-slate-600" />
                  Last login: {lastLoginDisplay}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 px-3 text-blue-600 justify-self-end self-start"
                onClick={() => setEditMode((v) => !v)}
                aria-label="Edit profile"
              >
                {editMode ? 'Close' : 'Edit Profile'}
              </Button>
            </div>

          {editMode && (
            <div className="space-y-2 rounded-md border border-slate-200 p-3 bg-slate-50">
              <div className="flex items-center gap-2 text-xs font-semibold text-slate-700 uppercase tracking-wide">
                <Pencil className="h-3.5 w-3.5" /> Edit profile
              </div>
              <div className="flex flex-col gap-2">
                <div className="flex gap-2">
                  <div className="flex-1">
                    <Label className="text-[11px] text-slate-600">First name</Label>
                    <Input value={draftFirst} onChange={(e) => setDraftFirst(e.target.value)} className="h-8 text-sm" />
                  </div>
                  <div className="flex-1">
                    <Label className="text-[11px] text-slate-600">Last name</Label>
                    <Input value={draftLast} onChange={(e) => setDraftLast(e.target.value)} className="h-8 text-sm" />
                  </div>
                </div>
                <div className="flex gap-2">
                  <div className="flex-1">
                    <Label className="text-[11px] text-slate-600">Role</Label>
                    <Input value={draftRole} onChange={(e) => setDraftRole(e.target.value)} className="h-8 text-sm" />
                  </div>
                  <div className="flex-1">
                    <Label className="text-[11px] text-slate-600">Phone</Label>
                    <Input value={draftPhone} onChange={(e) => setDraftPhone(e.target.value)} className="h-8 text-sm" />
                  </div>
                </div>
              </div>
              <div className="flex justify-end items-center gap-2">
                <Button variant="ghost" size="sm" className="h-8 px-3" onClick={() => setEditMode(false)} disabled={saving}>
                  Cancel
                </Button>
                <Button size="sm" className="h-8 px-3" onClick={saveDraft} disabled={saving}>
                  {saving ? 'Saving…' : 'Save'}
                </Button>
              </div>
            </div>
          )}
        </div>

        <Button variant="outline" size="sm" className="w-full justify-center" onClick={logout}>
          <LogOut className="h-4 w-4 mr-1.5" />
          Logout
        </Button>
      </PopoverContent>
    </Popover>
  );
}
