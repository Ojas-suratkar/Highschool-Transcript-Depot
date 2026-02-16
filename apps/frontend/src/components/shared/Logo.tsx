import { GraduationCap } from 'lucide-react';

export default function Logo({ compact = false, className = '' }: { compact?: boolean; className?: string }) {
  return (
    <div className={`inline-flex items-center gap-3 ${className}`}>
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-400 to-cyan-400 text-white">
        <GraduationCap className="h-5 w-5" />
      </div>
      {!compact && (
        <div className="leading-tight">
          <div className="font-semibold text-slate-900">Highschool Transcript Depot</div>
          <div className="text-xs text-slate-500">Admissions Transcript Automation</div>
        </div>
      )}
    </div>
  );
}
