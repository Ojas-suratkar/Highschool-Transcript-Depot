import { useState } from 'react';
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

export default function AddTermDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { addTerm } = useTerm();
  const [newTerm, setNewTerm] = useState({ name: '', season: '', year: '' });

  const handleAddTerm = () => {
    const id = `term-custom-${Date.now()}`;
    const year = Number(newTerm.year) || new Date().getFullYear();
    const semester = (newTerm.season as 'spring' | 'summer' | 'fall' | 'winter') || 'fall';
    addTerm({ id, name: newTerm.name || `Custom ${year}`, semester, year, isCurrent: false });
    toast.success('Term added successfully');
    setNewTerm({ name: '', season: '', year: '' });
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add New Term</DialogTitle>
          <DialogDescription>Create a new academic term for transcript processing</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="termName">Term Name</Label>
            <Input id="termName" placeholder="e.g., Fall 2025" value={newTerm.name} onChange={(e) => setNewTerm({ ...newTerm, name: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="season">Season</Label>
            <Select value={newTerm.season} onValueChange={(val) => setNewTerm({ ...newTerm, season: val })}>
              <SelectTrigger id="season">
                <SelectValue placeholder="Select season" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="spring">Spring</SelectItem>
                <SelectItem value="summer">Summer</SelectItem>
                <SelectItem value="fall">Fall</SelectItem>
                <SelectItem value="winter">Winter</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="year">Year</Label>
            <Input id="year" type="number" placeholder="2025" value={newTerm.year} onChange={(e) => setNewTerm({ ...newTerm, year: e.target.value })} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleAddTerm}>Add Term</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
