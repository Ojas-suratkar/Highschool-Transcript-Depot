import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useTerm } from '@/contexts/TermContext';
import { toast } from 'sonner';
import { createTerm } from '../../lib/api/SemesterTerm';
import { useAuth } from '@/contexts/AuthContext';

export default function AddTermDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { terms, addTerm } = useTerm();
  const { user } = useAuth();

  const [term, setTerm] = useState('');
  const [year, setYear] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Reset to empty every time dialog opens
  useEffect(() => {
    if (open) {
      setTerm('');
      setYear('');
      setError(null);
    }
  }, [open]);

  const handleAdd = async () => {
    setError(null);

    if (!term) { setError('Please select a term.'); return; }
    if (!year) { setError('Please enter a year.'); return; }

    const institutionId = user?.institution?.id ?? user?.institution_id;
    const createdByUserId = user?.id;

    if (!institutionId || !createdByUserId) {
      setError('Unable to determine your institution.');
      return;
    }

    const term_name = `${term.charAt(0).toUpperCase() + term.slice(1)} ${year}`;
    const normalize = (s: string) => s.trim().toLowerCase();

    if (terms.some(t => normalize(t.term_name) === normalize(term_name))) {
      setError(`${term_name} already exists.`);
      return;
    }

    setSaving(true);
    try {
      const saved = await createTerm({
        term_name,
        term: term as any,
        year: Number(year),
        institution_id: institutionId,
        created_by_user_id: createdByUserId,
      });

      addTerm({
        id: String(saved.id),
        term_name: saved.term_name,
        term: saved.term,
        year: saved.year,
        isCurrent: false,
      });

      toast.success(`${term_name} added`);
      onOpenChange(false);
    } catch {
      setError('Failed to create term. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Add New Term</DialogTitle>
          <DialogDescription>Select a semester and enter a year to create a new academic term.</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label>Semester</Label>
            <Select value={term} onValueChange={setTerm}>
              <SelectTrigger>
                <SelectValue placeholder="Select semester…" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="spring">Spring</SelectItem>
                <SelectItem value="summer">Summer</SelectItem>
                <SelectItem value="fall">Fall</SelectItem>
                <SelectItem value="winter">Winter</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label>Year</Label>
            <Input
              type="number"
              placeholder="e.g. 2025"
              value={year}
              onChange={(e) => setYear(e.target.value)}
            />
          </div>

          {term && year && (
            <p className="text-sm text-muted-foreground">
              Term: <span className="font-medium text-foreground">{term.charAt(0).toUpperCase() + term.slice(1)} {year}</span>
            </p>
          )}

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>Cancel</Button>
          <Button onClick={handleAdd} disabled={!term || !year || saving}>
            {saving ? 'Adding…' : 'Add Term'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
